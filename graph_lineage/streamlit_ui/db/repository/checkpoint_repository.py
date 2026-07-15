"""Repository for Checkpoint entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.data_classes.neo4j.nodes.checkpoint import Checkpoint
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.neo4j_client.client import StreamlitNeo4jClient

logger = logging.getLogger(__name__)


class CheckpointRepository:
    """Data access layer for Checkpoint entity."""

    def __init__(self, db_client: StreamlitNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client

    async def list_all(
        self,
        experiment_id: Optional[str] = None,
        usable_only: bool = False
    ) -> list[Checkpoint]:
        """List all checkpoints with default limit of 100.
        
        Args:
            experiment_id: Optional experiment ID to filter by.
            usable_only: Only return usable checkpoints if True.
            
        Returns:
            List of Checkpoint objects.
        """
        return await self.list_with_limit(
            limit=100,
            offset=0,
            experiment_id=experiment_id,
            usable_only=usable_only
        )

    async def list_with_limit(
        self,
        limit: int = 100,
        offset: int = 0,
        experiment_id: Optional[str] = None,
        usable_only: bool = False
    ) -> list[Checkpoint]:
        """List checkpoints with pagination support.
        
        Args:
            limit: Maximum number of checkpoints to return.
            offset: Number of checkpoints to skip (for pagination).
            experiment_id: Optional experiment ID to filter by.
            usable_only: Only return usable checkpoints if True.
            
        Returns:
            List of Checkpoint objects.
        """
        where_clauses = []
        params = {"limit": limit, "offset": offset}
        if experiment_id:
            where_clauses.append("e.exp_id = $experiment_id")
            params["experiment_id"] = experiment_id
        if usable_only:
            where_clauses.append("c.is_usable = true")
        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        query = f"""
        MATCH (c:Checkpoint)-[:PRODUCED_BY]->(e:Experiment)
        {where}
        RETURN c.id as id, c.name as name, c.epoch as epoch, c.run as run,
               c.metrics as metrics, c.uri as uri,
               c.derived_from as derived_from,
               c.is_usable as is_usable, c.is_merging as is_merging,
               c.created_at as created_at, c.updated_at as updated_at
        ORDER BY c.created_at DESC
        SKIP $offset LIMIT $limit
        """
        results = await self.db.run_list(query, **params)
        return [Checkpoint(**row) for row in results]

    async def get_by_id(self, ckp_id: str) -> Optional[Checkpoint]:
        """Get checkpoint by ID.

        Args:
            ckp_id: Checkpoint ID.

        Returns:
            Checkpoint object or None if not found.
        """
        query = """
        MATCH (c:Checkpoint {id: $ckp_id})
        RETURN c.id as id, c.name as name, c.epoch as epoch, c.run as run,
               c.metrics as metrics, c.uri as uri,
               c.derived_from as derived_from,
               c.is_usable as is_usable, c.is_merging as is_merging,
               c.created_at as created_at, c.updated_at as updated_at
        """
        result = await self.db.run_single(query, ckp_id=ckp_id)
        return Checkpoint(**result) if result else None

    async def update_uri(self, ckp_id: str, new_uri: str) -> Checkpoint:
        """Update checkpoint URI.

        Args:
            ckp_id: Checkpoint ID.
            new_uri: New URI value.

        Returns:
            Updated Checkpoint object.

        Raises:
            UIError: If checkpoint not found.
        """
        now = datetime.utcnow().isoformat()
        query = """
        MATCH (c:Checkpoint {id: $ckp_id})
        SET c.uri = $new_uri, c.updated_at = $updated_at
        RETURN c.id as id, c.name as name, c.epoch as epoch, c.run as run,
               c.metrics as metrics, c.uri as uri,
               c.derived_from as derived_from,
               c.is_usable as is_usable, c.is_merging as is_merging,
               c.created_at as created_at, c.updated_at as updated_at
        """
        result = await self.db.run_single(query, ckp_id=ckp_id, new_uri=new_uri, updated_at=now)
        if not result:
            raise UIError("Checkpoint not found")
        return Checkpoint(**result)

    async def set_usable(self, ckp_id: str, is_usable: bool) -> Checkpoint:
        """Toggle checkpoint usability flag.

        Args:
            ckp_id: Checkpoint ID.
            is_usable: New usability state.

        Returns:
            Updated Checkpoint object.

        Raises:
            UIError: If checkpoint not found.
        """
        now = datetime.utcnow().isoformat()
        query = """
        MATCH (c:Checkpoint {id: $ckp_id})
        SET c.is_usable = $is_usable, c.updated_at = $updated_at
        RETURN c.id as id, c.name as name, c.epoch as epoch, c.run as run,
               c.metrics as metrics, c.uri as uri,
               c.derived_from as derived_from,
               c.is_usable as is_usable, c.is_merging as is_merging,
               c.created_at as created_at, c.updated_at as updated_at
        """
        result = await self.db.run_single(query, ckp_id=ckp_id, is_usable=is_usable, updated_at=now)
        if not result:
            raise UIError("Checkpoint not found")
        return Checkpoint(**result)

    async def get_dependencies(self, ckp_id: str) -> list[dict]:
        """Get experiments that STARTED_FROM this checkpoint.

        Args:
            ckp_id: Checkpoint ID.

        Returns:
            List of dependent experiment records.
        """
        query = """
        MATCH (e:Experiment)-[:STARTED_FROM]->(c:Checkpoint {id: $ckp_id})
        RETURN e.exp_id as exp_id, e.status as status, e.description as description
        """
        return await self.db.run_list(query, ckp_id=ckp_id)
