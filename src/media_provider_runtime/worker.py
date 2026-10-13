# Copyright 2026 Yilei Bi
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import dataclasses
import enum
import json
import logging
import sys
from importlib import metadata
from typing import Any

from media_provider_sdk import (
    MediaProvider,
    PLUGIN_ENTRY_POINT_GROUP,
    ProviderError,
)

from media_provider_runtime.protocol import (
    PROTOCOL_VERSION,
)


logger = logging.getLogger(__name__)

# Keep the original stdout exclusively for IPC responses.
# main() redirects normal Python print() calls to stderr so plugin output
# does not corrupt the NDJSON protocol stream.
_IPC_STDOUT = sys.stdout


class WorkerState:
    def __init__(self) -> None:
        self.provider: MediaProvider | None = None


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(value, enum.Enum):
        return value.value

    if dataclasses.is_dataclass(value):
        return {
            key: _to_jsonable(item)
            for key, item in dataclasses.asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): _to_jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            _to_jsonable(item)
            for item in value
        ]

    model_dump = getattr(
        value,
        "model_dump",
        None,
    )

    if callable(model_dump):
        return _to_jsonable(
            model_dump(mode="json")
        )

    raise TypeError(
        "Value is not JSON serializable: "
        f"{type(value).__name__}"
    )


def _serialize_error(
    exception: Exception,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "type": type(exception).__name__,
        "message": str(exception),
    }

    if isinstance(exception, ProviderError):
        error["code"] = exception.code
        error["retryable"] = exception.retryable
        error["details"] = _to_jsonable(
            exception.details
        )

    return error


def _write_response(
    payload: dict[str, Any],
) -> None:
    _IPC_STDOUT.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )

    _IPC_STDOUT.flush()


def _find_provider_class(
    entry_point_name: str,
) -> type[MediaProvider]:
    normalized_name = (
        entry_point_name.strip().lower()
    )

    entry_points = metadata.entry_points(
        group=PLUGIN_ENTRY_POINT_GROUP
    )

    for entry_point in entry_points:
        if (
            entry_point.name.strip().lower()
            != normalized_name
        ):
            continue

        provider_class = entry_point.load()

        if not isinstance(provider_class, type):
            raise TypeError(
                "Provider entry point must resolve "
                "to a class"
            )

        if not issubclass(
            provider_class,
            MediaProvider,
        ):
            raise TypeError(
                "Provider class must inherit "
                "MediaProvider"
            )

        return provider_class

    raise LookupError(
        "Provider entry point not found: "
        f"{entry_point_name}"
    )


async def _initialize(
    state: WorkerState,
    params: dict[str, Any],
) -> dict[str, Any]:
    entry_point_name = params.get(
        "entry_point_name"
    )

    if not isinstance(
        entry_point_name,
        str,
    ) or not entry_point_name.strip():
        raise ValueError(
            "entry_point_name is required"
        )

    settings = params.get("settings") or {}
    secrets = params.get("secrets") or {}

    if not isinstance(settings, dict):
        raise TypeError(
            "settings must be an object"
        )

    if not isinstance(secrets, dict):
        raise TypeError(
            "secrets must be an object"
        )

    provider_class = _find_provider_class(
        entry_point_name
    )

    candidate = provider_class(
        settings=settings,
        secrets=secrets,
    )

    try:
        await candidate.validate_config()
    except Exception:
        try:
            await candidate.close()
        except Exception:
            logger.exception(
                "Failed to close provider after "
                "initialization failure"
            )
        raise

    previous = state.provider
    state.provider = candidate

    if previous is not None:
        try:
            await previous.close()
        except Exception:
            logger.exception(
                "Failed to close previous provider"
            )

    return {
        "provider_type": candidate.provider_type,
        "display_name": candidate.display_name,
        "capabilities": _to_jsonable(
            candidate.capabilities
        ),
    }


def _require_provider(
    state: WorkerState,
) -> MediaProvider:
    if state.provider is None:
        raise RuntimeError(
            "Worker has not been initialized"
        )

    return state.provider


async def _dispatch(
    state: WorkerState,
    method: str,
    params: dict[str, Any],
) -> tuple[Any, bool]:
    # Shutdown must work even before initialize().
    if method == "shutdown":
        return None, True

    if method == "initialize":
        result = await _initialize(
            state,
            params,
        )

        return result, False

    provider = _require_provider(
        state
    )

    if method == "capabilities":
        return (
            _to_jsonable(
                provider.capabilities
            ),
            False,
        )

    if method == "search":
        query = params.get("query")
        limit = params.get("limit", 20)

        if not isinstance(query, str):
            raise TypeError(
                "query must be a string"
            )

        if not isinstance(limit, int):
            raise TypeError(
                "limit must be an integer"
            )

        result = await provider.search(
            query,
            limit=limit,
        )

        return _to_jsonable(result), False

    if method == "get_stream":
        provider_item_id = params.get(
            "provider_item_id"
        )

        if not isinstance(
            provider_item_id,
            str,
        ):
            raise TypeError(
                "provider_item_id must be a string"
            )

        result = await provider.get_stream(
            provider_item_id
        )

        return _to_jsonable(result), False

    if method == "get_preview_stream":
        provider_item_id = params.get(
            "provider_item_id"
        )

        if not isinstance(
            provider_item_id,
            str,
        ):
            raise TypeError(
                "provider_item_id must be a string"
            )

        result = (
            await provider.get_preview_stream(
                provider_item_id
            )
        )

        return _to_jsonable(result), False

    if method == "get_lyrics":
        provider_item_id = params.get(
            "provider_item_id"
        )

        if not isinstance(
            provider_item_id,
            str,
        ):
            raise TypeError(
                "provider_item_id must be a string"
            )

        result = await provider.get_lyrics(
            provider_item_id
        )

        return _to_jsonable(result), False

    raise ValueError(
        f"Unknown worker method: {method}"
    )


async def run_worker() -> None:
    state = WorkerState()

    try:
        while True:
            line = await asyncio.to_thread(
                sys.stdin.readline
            )

            if line == "":
                break

            line = line.strip()

            if not line:
                continue

            request_id = ""

            try:
                request = json.loads(line)

                if not isinstance(request, dict):
                    raise TypeError(
                        "request must be an object"
                    )

                raw_request_id = request.get(
                    "id",
                    "",
                )

                if not isinstance(
                    raw_request_id,
                    str,
                ):
                    raise TypeError(
                        "id must be a string"
                    )

                request_id = raw_request_id

                protocol_version = request.get(
                    "protocol_version"
                )

                if (
                    protocol_version
                    != PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "Unsupported protocol version: "
                        f"{protocol_version}"
                    )

                method = request.get("method")
                params = request.get(
                    "params",
                    {},
                )

                if not isinstance(method, str):
                    raise TypeError(
                        "method must be a string"
                    )

                if not isinstance(params, dict):
                    raise TypeError(
                        "params must be an object"
                    )

                result, should_shutdown = (
                    await _dispatch(
                        state,
                        method,
                        params,
                    )
                )

                _write_response(
                    {
                        "protocol_version": (
                            PROTOCOL_VERSION
                        ),
                        "id": request_id,
                        "ok": True,
                        "result": result,
                    }
                )

                if should_shutdown:
                    break

            except Exception as exception:
                logger.exception(
                    "Worker request failed"
                )

                _write_response(
                    {
                        "protocol_version": (
                            PROTOCOL_VERSION
                        ),
                        "id": request_id,
                        "ok": False,
                        "error": _serialize_error(
                            exception
                        ),
                    }
                )

    finally:
        if state.provider is not None:
            try:
                await state.provider.close()
            except Exception:
                logger.exception(
                    "Failed to close provider"
                )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
    )

    # Preserve stdout exclusively for IPC. Normal print() output from
    # Python plugin code is redirected to stderr.
    sys.stdout = sys.stderr

    asyncio.run(
        run_worker()
    )
