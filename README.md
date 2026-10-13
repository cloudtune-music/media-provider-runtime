# Media Provider Runtime

Isolated worker runtime for Media Provider Server plugins.

`media-provider-runtime` is the execution layer used by
[Media Provider Server](https://github.com/cloudtune-music/media-provider-server)
to load and execute provider plugins inside isolated Python environments.

It is **not** the public API for developing provider plugins.

Plugin developers should use
[`media-provider-sdk`](https://github.com/cloudtune-music/media-provider-sdk)
instead.

---

## Overview

Media Provider Server supports external provider plugins.

Each plugin may have its own Python dependencies, versions, authentication
libraries, SDKs, and media-source integrations.

To prevent those dependencies from being installed into the Server's Python
environment, Media Provider Server creates isolated Python environments for
plugins.

`media-provider-runtime` is installed into those environments and acts as the
worker process between the Server and the provider plugin.

A typical plugin environment looks like:

```text
Plugin environment
│
├── media-provider-sdk
├── media-provider-runtime
├── provider plugin
└── plugin dependencies
```

For example:

```text
YouTube Provider environment
│
├── media-provider-sdk
├── media-provider-runtime
├── cloudtune-yt-provider
└── yt-dlp
```

The Server communicates with the Runtime worker using IPC.

The Runtime then calls the provider implementation through the stable contract
defined by `media-provider-sdk`.

---

## Architecture

```text
                         Client
                           │
                           │ HTTP
                           ▼
                ┌─────────────────────┐
                │ Media Provider      │
                │ Server              │
                │                     │
                │ FastAPI / DB / HLS  │
                └──────────┬──────────┘
                           │
                           │ IPC
                           ▼
                ┌─────────────────────┐
                │ Media Provider      │
                │ Runtime             │
                │                     │
                │ Worker Process      │
                └──────────┬──────────┘
                           │
                           │ SDK Contract
                           ▼
                ┌─────────────────────┐
                │ Provider Plugin     │
                │                     │
                │ YT / WebDAV / ...  │
                └──────────┬──────────┘
                           │
                           ▼
                     Media Source
```

The major responsibilities are intentionally separated.

### Media Provider Server

The Server owns:

- HTTP APIs
- authentication and users
- database access
- provider configuration
- plugin discovery and lifecycle
- search orchestration
- stable track IDs
- playback policy
- DIRECT / HLS decisions
- HLS packaging
- worker lifecycle management

### Media Provider Runtime

The Runtime owns:

- worker process execution
- provider entry-point discovery
- provider loading
- provider initialization
- request dispatch
- result serialization
- error serialization
- controlled provider shutdown

### Media Provider SDK

The SDK defines the stable contract between Runtime and provider plugins.

It includes types such as:

```python
MediaProvider
ProviderCapabilities
ProviderSearchResult
ProviderStream
ProviderLyrics
```

### Provider Plugin

A Provider Plugin owns source-specific behavior such as:

- searching a media source
- resolving media streams
- authentication with the source
- optional preview streams
- optional lyrics
- source-specific metadata

---

## Relationship to Media Provider SDK

Provider plugins should depend on:

```text
media-provider-sdk
```

For example:

```python
from media_provider_sdk import (
    MediaProvider,
    ProviderSearchResult,
    ProviderStream,
)


class ExampleProvider(MediaProvider):
    provider_type = "EXAMPLE"
    display_name = "Example Provider"

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        ...

    async def get_stream(
        self,
        provider_item_id: str,
    ) -> ProviderStream:
        ...
```

Provider plugins should **not** import Runtime internals:

```python
# Do not do this in a provider plugin
import media_provider_runtime
```

The Runtime is an implementation detail of Media Provider Server.

---

## Plugin Isolation

Each installed plugin is assigned an isolated Python environment.

A typical runtime directory may look like:

```text
plugin-runtime/
└── <plugin-id>/
    └── <artifact-hash>/
        └── .venv/
            ├── media-provider-sdk
            ├── media-provider-runtime
            ├── provider plugin
            └── plugin dependencies
```

The environment is associated with:

```text
plugin_id + artifact_hash
```

This allows a new plugin artifact to receive a new isolated environment while
preserving stable plugin identity at the Server level.

Different plugins can therefore use different versions of their own
dependencies without sharing the main Server Python environment.

For example:

```text
Provider A
└── dependency-x 1.x

Provider B
└── dependency-x 2.x
```

These dependencies remain isolated from each other.

---

## Worker Processes

Provider implementations execute in worker processes rather than being imported
directly into the Media Provider Server process.

A worker is normally associated with a configured provider instance.

The lifecycle is conceptually:

```text
Provider requested
        │
        ▼
Resolve plugin artifact
        │
        ▼
Create or reuse isolated environment
        │
        ▼
Start worker process
        │
        ▼
Initialize provider
        │
        ▼
Handle provider operations
        │
        ▼
Reuse worker
        │
        ▼
Shutdown
```

Media Provider Server owns this lifecycle.

Provider plugins do not create or manage worker processes themselves.

---

## IPC Protocol

Media Provider Server communicates with the worker through a structured
request/response protocol.

The Runtime reserves standard output for protocol messages.

Ordinary plugin output is redirected to standard error so that plugin logging or
`print()` calls do not corrupt the IPC stream.

Supported worker operations include:

```text
initialize
capabilities
search
get_stream
get_preview_stream
get_lyrics
shutdown
```

The provider-level method contracts are defined by `media-provider-sdk`.

---

## Initialization

The Server starts a worker and initializes a provider with information such as:

```text
entry point
settings
secrets
```

The Runtime loads the requested provider implementation from the isolated
environment and creates the provider instance.

Provider settings and secrets are then passed through the SDK-defined provider
constructor.

---

## Provider Metadata Discovery

The Runtime can inspect an installed Python distribution and report the provider
entry points exposed by that distribution.

This allows Media Provider Server to discover provider metadata without
importing third-party provider code into the main Server process.

Example:

```bash
python -m media_provider_runtime \
    --describe-distribution cloudtune-yt-provider
```

Example output:

```json
{
  "package_name": "cloudtune-yt-provider",
  "package_version": "0.1.0",
  "providers": [
    {
      "entry_point_name": "yt",
      "provider_type": "YT",
      "display_name": "YouTube Provider"
    }
  ]
}
```

The exact display name depends on the provider implementation.

---

## Provider Entry Points

Provider plugins are discovered using the Python entry-point group:

```text
media_provider.providers
```

A provider plugin can register an implementation in its `pyproject.toml`:

```toml
[project.entry-points."media_provider.providers"]
example = "example_provider.provider:ExampleProvider"
```

A single plugin distribution may expose multiple provider implementations:

```toml
[project.entry-points."media_provider.providers"]
provider_a = "example_provider.provider_a:ProviderA"
provider_b = "example_provider.provider_b:ProviderB"
```

Each provider is identified by its plugin and entry-point name.

---

## Provider Operations

The Runtime dispatches provider operations defined by the SDK.

### Search

```text
search
```

Calls the provider's search implementation and returns serialized
`ProviderSearchResult` objects.

### Stream Resolution

```text
get_stream
```

Requests a media stream from the provider.

The provider returns a `ProviderStream` describing the source stream.

Playback policy remains the responsibility of Media Provider Server.

For example, a provider may return a direct media source:

```text
Provider
    │
    ▼
DIRECT source
    │
    ▼
Media Provider Server Playback Policy
    │
    ├── DIRECT to client
    │
    └── Server-side HLS packaging
```

If a provider returns native HLS, the Server may pass it through without
repackaging it.

### Preview

```text
get_preview_stream
```

Requests a preview stream when the provider supports one.

### Lyrics

```text
get_lyrics
```

Requests lyrics when supported by the provider.

### Capabilities

```text
capabilities
```

Returns the capabilities declared by the provider.

---

## Error Handling

Provider failures are returned to Media Provider Server as structured errors.

Runtime error information may include:

```text
type
message
code
retryable
details
```

The Server can then map supported Runtime errors back to SDK-level provider
exceptions.

Examples of SDK-level errors include:

```text
ProviderConfigurationError
ProviderAuthenticationError
ProviderPermissionError
ProviderItemNotFoundError
ProviderSearchError
ProviderStreamError
ProviderTimeoutError
ProviderRateLimitError
ProviderUnavailableError
ProviderUnsupportedOperationError
ProviderInvalidResponseError
```

This prevents source-specific exceptions from leaking directly into the Server
business layer.

---

## Installation

Most users should **not install this package manually**.

Media Provider Server distributions bundle a compatible
`media-provider-runtime` wheel and automatically install it into isolated plugin
environments.

Normal Server users only need to deploy Media Provider Server.

Provider developers normally only need:

```text
media-provider-sdk
```

---

## Development

Requirements:

```text
Python 3.12+
```

Clone the repository:

```bash
git clone https://github.com/cloudtune-music/media-provider-runtime.git
cd media-provider-runtime
```

Create the development environment:

```bash
uv sync
```

Verify the package:

```bash
uv run python -c "import media_provider_runtime; print(media_provider_runtime)"
```

Run tests if available:

```bash
uv run pytest
```

---

## SDK Dependency

Runtime depends on a compatible version of `media-provider-sdk`.

For the `0.1.x` Runtime series:

```toml
dependencies = [
    "media-provider-sdk>=0.1.0,<0.2.0",
]
```

During source development, `uv` may obtain the SDK from its versioned GitHub
repository.

For example:

```toml
[tool.uv.sources]
media-provider-sdk = {
    git = "https://github.com/cloudtune-music/media-provider-sdk.git",
    tag = "v0.1.0"
}
```

The published Runtime wheel itself declares the normal package dependency on
`media-provider-sdk`.

Media Provider Server is responsible for providing compatible SDK and Runtime
wheels when building isolated plugin environments.

---

## Building

Build the package with:

```bash
uv build
```

The build creates:

```text
dist/
├── media_provider_runtime-0.1.0-py3-none-any.whl
└── media_provider_runtime-0.1.0.tar.gz
```

The wheel can be published as a GitHub Release asset.

The `dist/` directory should normally not be committed to the repository.

---

## Release Model

A typical release contains:

```text
GitHub Repository
├── source code
├── README.md
├── LICENSE
├── pyproject.toml
└── ...

GitHub Release
└── v0.1.0
    └── media_provider_runtime-0.1.0-py3-none-any.whl
```

Media Provider Server releases should use known compatible SDK and Runtime
versions.

For example:

```text
Media Provider Server 0.1.0
├── Media Provider SDK 0.1.0
└── Media Provider Runtime 0.1.0
```

Runtime versions are selected by the Server distribution.

Provider plugins should not depend directly on Runtime versions.

---

## Security

Plugin isolation provides dependency and process isolation.

It is **not a security sandbox**.

A provider plugin may still be able to access resources available to the
operating-system user or container running the worker.

Examples may include:

```text
filesystem access
network access
environment variables
process-visible resources
```

Only install provider plugins from sources you trust.

Future Server deployments may add stronger operating-system or container-level
sandboxing independently of the Runtime API.

---

## Who Should Use This Repository?

### Media Provider Server developers

Yes.

This repository contains the worker execution layer used by Media Provider
Server.

### Provider plugin developers

Usually no.

Provider developers should build against:

[Media Provider SDK](https://github.com/cloudtune-music/media-provider-sdk)

### Media Provider Server users

Normally no direct interaction is required.

The Server distribution manages Runtime installation automatically.

---

## Related Projects

### Media Provider Server

Self-hosted media source gateway and provider orchestration server.

https://github.com/cloudtune-music/media-provider-server

### Media Provider SDK

Public Python contract for developing provider plugins.

https://github.com/cloudtune-music/media-provider-sdk

---

## License

Copyright 2026 Yilei Bi

Licensed under the Apache License, Version 2.0.

See [LICENSE](LICENSE) for details.