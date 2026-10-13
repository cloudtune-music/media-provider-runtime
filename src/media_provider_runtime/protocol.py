# Copyright 2026 Yilei Bi
# SPDX-License-Identifier: Apache-2.0

from typing import (
    Any,
    Literal,
    NotRequired,
    TypedDict,
)


PROTOCOL_VERSION = 1


WorkerMethod = Literal[
    "initialize",
    "capabilities",
    "search",
    "get_stream",
    "get_preview_stream",
    "get_lyrics",
    "shutdown",
]


class WorkerRequest(TypedDict):
    protocol_version: int
    id: str
    method: WorkerMethod
    params: dict[str, Any]


class WorkerError(TypedDict):
    type: str
    message: str
    code: NotRequired[str]
    retryable: NotRequired[bool]
    details: NotRequired[dict[str, Any]]


class WorkerSuccessResponse(TypedDict):
    protocol_version: int
    id: str
    ok: Literal[True]
    result: Any


class WorkerErrorResponse(TypedDict):
    protocol_version: int
    id: str
    ok: Literal[False]
    error: WorkerError


WorkerResponse = (
    WorkerSuccessResponse
    | WorkerErrorResponse
)
