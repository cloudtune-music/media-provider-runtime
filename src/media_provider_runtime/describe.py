# Copyright 2026 Yilei Bi
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
from importlib import metadata
from typing import Any

from media_provider_sdk import (
    MediaProvider,
    PLUGIN_ENTRY_POINT_GROUP,
)


def describe_distribution(
    distribution_name: str,
) -> dict[str, Any]:
    distribution = metadata.distribution(
        distribution_name
    )

    providers: list[dict[str, Any]] = []

    for entry_point in distribution.entry_points:
        if (
            entry_point.group
            != PLUGIN_ENTRY_POINT_GROUP
        ):
            continue

        provider_class = entry_point.load()

        if not isinstance(
            provider_class,
            type,
        ):
            raise TypeError(
                "Provider entry point must "
                "resolve to a class"
            )

        if not issubclass(
            provider_class,
            MediaProvider,
        ):
            raise TypeError(
                "Provider class must inherit "
                "MediaProvider"
            )

        provider_type = getattr(
            provider_class,
            "provider_type",
            None,
        )

        if (
            not isinstance(provider_type, str)
            or not provider_type.strip()
        ):
            raise ValueError(
                "Provider class must define "
                "provider_type"
            )

        provider_type = (
            provider_type
            .strip()
            .upper()
        )

        display_name = (
            getattr(
                provider_class,
                "display_name",
                None,
            )
            or provider_type
        )

        providers.append(
            {
                "entry_point_name": (
                    entry_point.name
                    .strip()
                    .lower()
                ),
                "provider_type": (
                    provider_type
                ),
                "display_name": (
                    display_name
                ),
            }
        )

    if not providers:
        raise RuntimeError(
            "Distribution exposes no "
            "Media Provider entry points"
        )

    return {
        "package_name": (
            distribution.metadata["Name"]
        ),
        "package_version": (
            distribution.version
        ),
        "providers": providers,
    }


def print_distribution_description(
    distribution_name: str,
) -> None:
    # Plugin import 中的 print() 不能污染 JSON stdout。
    ipc_stdout = sys.stdout
    sys.stdout = sys.stderr

    result = describe_distribution(
        distribution_name
    )

    ipc_stdout.write(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )

    ipc_stdout.flush()