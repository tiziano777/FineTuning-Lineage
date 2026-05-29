# storage/ Module — Storage Provider Abstraction

## Overview

Abstract away storage details (local filesystem, S3, NFS, etc.) so checkpoint/metrics URIs work anywhere.

**Location:** `graph_lineage/storage/`

## Public API

```python
from graph_lineage.storage import (
    StorageProvider,      # ABC
    LocalStorageProvider, # Filesystem
    StorageResolver,      # URI scheme → provider
)
```

## Components

### StorageProvider (ABC)
```python
class StorageProvider(ABC):
    @abstractmethod
    def resolve_path(self, uri: str) -> str:
        """Convert URI to local path or raise error."""
    
    @abstractmethod
    def exists(self, uri: str) -> bool:
        """Check if resource exists."""
    
    @abstractmethod
    def read(self, uri: str) -> bytes:
        """Read resource."""
    
    @abstractmethod
    def write(self, uri: str, data: bytes) -> None:
        """Write resource."""
```

### LocalStorageProvider
```python
class LocalStorageProvider(StorageProvider):
    """Handles local filesystem URIs."""
    
    def resolve_path(self, uri: str) -> str:
        # uri: "file:///nfs/checkpoints/e-001_c5.pt"
        # Returns: "/nfs/checkpoints/e-001_c5.pt"
```

### StorageResolver
```python
class StorageResolver:
    @staticmethod
    def get_provider(uri: str) -> StorageProvider:
        # Detects scheme (file://, s3://, etc.)
        # Returns appropriate provider
        
        if uri.startswith("file://"):
            return LocalStorageProvider()
        elif uri.startswith("s3://"):
            return S3StorageProvider()  # Future
        else:
            raise ValueError(f"Unknown URI scheme: {uri}")
```

---

## Use Cases

**Resolve checkpoint path:**
```python
from graph_lineage.storage import StorageResolver

resolver = StorageResolver()
provider = resolver.get_provider(checkpoint_uri)
path = provider.resolve_path(checkpoint_uri)
# path = "/nfs/checkpoints/e-001_c5.pt"
```

**Future-proof for multi-backend:**
- Add `S3StorageProvider` → S3 checkpoints automatically work
- No changes needed to rest of codebase

---

## Testing

Location: `tests/test_storage.py`

---

## See Also

- [lineage.md](lineage.md) — How metrics/checkpoint URIs are captured

