"""Universal URI resolver — maps URI prefixes to storage providers.

Reads `.storage-config.yml` for mount/prefix mappings.
Default: all paths → LocalStorageProvider.

Config format (.storage-config.yml):
```yaml
mounts:
  - prefix: "/mnt/shared"
    provider: "local"
    base_path: "/mnt/shared"
  - prefix: "s3://"
    provider: "s3"
    bucket: "my-bucket"
default_provider: "local"
```
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from graph_lineage.storage.local_provider import LocalStorageProvider
from graph_lineage.storage.provider import StorageProvider

logger = logging.getLogger(__name__)


class StorageResolver:
    """Resolves URIs to appropriate StorageProvider instances."""

    def __init__(self, config_path: str | None = None):
        """Initialize resolver.

        Args:
            config_path: Path to .storage-config.yml.
                         If None, uses LocalStorageProvider for everything.
        """
        self._providers: dict[str, StorageProvider] = {}
        self._prefix_map: list[tuple[str, str]] = []  # (prefix, provider_key)
        self._default = LocalStorageProvider()

        if config_path:
            self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        """Load storage config from YAML file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning("Storage config not found: %s — using local provider", config_path)
            return

        with open(path) as f:
            config = yaml.safe_load(f)

        if not config or "mounts" not in config:
            return

        for mount in config["mounts"]:
            prefix = mount["prefix"]
            provider_type = mount.get("provider", "local")
            key = f"{provider_type}:{prefix}"

            if provider_type == "local":
                base = mount.get("base_path", prefix)
                self._providers[key] = LocalStorageProvider(base_path=base)
            else:
                logger.warning("Unsupported provider type: %s (prefix: %s)", provider_type, prefix)
                continue

            self._prefix_map.append((prefix, key))

        # Sort by prefix length descending (most specific first)
        self._prefix_map.sort(key=lambda x: len(x[0]), reverse=True)

    def resolve(self, uri: str) -> tuple[StorageProvider, str]:
        """Resolve URI to (provider, relative_path).

        Args:
            uri: File path or URI (e.g., "/mnt/shared/data.json", "s3://bucket/key").

        Returns:
            Tuple of (StorageProvider, resolved_path).
        """
        for prefix, key in self._prefix_map:
            if uri.startswith(prefix):
                provider = self._providers[key]
                relative = uri[len(prefix):].lstrip("/")
                return provider, relative

        return self._default, uri

    def exists(self, uri: str) -> bool:
        """Check if URI exists via resolved provider."""
        provider, path = self.resolve(uri)
        return provider.exists(path)

    def read_text(self, uri: str) -> str:
        """Read text from URI via resolved provider."""
        provider, path = self.resolve(uri)
        return provider.read_text(path)

    def write_text(self, uri: str, content: str) -> None:
        """Write text to URI via resolved provider."""
        provider, path = self.resolve(uri)
        provider.write_text(path, content)

    def is_writable(self, uri: str) -> bool:
        """Check if URI is writable."""
        provider, path = self.resolve(uri)
        return provider.is_writable(path)

    def validate_uris(self, uris: list[str]) -> dict[str, str | None]:
        """Validate list of URIs. Returns {uri: error_msg} (None = ok).

        Args:
            uris: List of URIs to validate.

        Returns:
            Dict mapping each URI to error string (None if valid/reachable).
        """
        results: dict[str, str | None] = {}
        for uri in uris:
            try:
                provider, path = self.resolve(uri)
                parent_dir = str(Path(path).parent) if not provider.is_dir(path) else path
                if not provider.exists(parent_dir) and not provider.exists(path):
                    results[uri] = f"Path not found: {uri}"
                elif not provider.is_writable(parent_dir):
                    results[uri] = f"Path not writable: {uri}"
                else:
                    results[uri] = None
            except Exception as e:
                results[uri] = f"Cannot access {uri}: {e}"
        return results
