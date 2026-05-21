"""Storage abstraction layer for filesystem-agnostic operations.

Provides StorageProvider ABC + LocalStorageProvider implementation.
Future: SSHStorageProvider, S3StorageProvider.
"""

from graph_lineage.storage.provider import StorageProvider
from graph_lineage.storage.local_provider import LocalStorageProvider
from graph_lineage.storage.resolver import StorageResolver

__all__ = ["StorageProvider", "LocalStorageProvider", "StorageResolver"]
