"""Repository for Checkpoint entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class CheckpointRepository:
    """Data access layer for Checkpoint entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client

    async def list_all(self, experiment_id: Optional[str] = None, usable_only: bool = False) -> list[dict]:
        """List checkpoints with parent experiment and used_by info."""
        where_clauses = []
        params = {}
        if experiment_id:
            where_clauses.append("e.exp_id = $experiment_id")
            params["experiment_id"] = experiment_id
        if usable_only:
            where_clauses.append("c.is_usable = true")
        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        query = f"""
        MATCH (c:Checkpoint)-[:PRODUCED_BY]->(e:Experiment)
        {where}
        OPTIONAL MATCH (e2:Experiment)-[:STARTED_FROM]->(c)
        WITH c, e, COLLECT(e2.exp_id) as used_by_exps
        RETURN c.ckp_id as ckp_id, c.epoch as epoch, c.run as run,
               c.metrics_snapshot as metrics_snapshot, c.uri as uri,
               c.is_usable as is_usable, c.created_at as created_at,
               e.exp_id as parent_exp, used_by_exps
        ORDER BY c.created_at DESC
        LIMIT 100
        """
        return await self.db.run_list(query, **params)

    async def get_by_id(self, ckp_id: str) -> Optional[dict]:
        """Get checkpoint by ID.

        Args:
            ckp_id: Checkpoint ID.

        Returns:
            Checkpoint data or None if not found.
        """
        query = "MATCH (c:Checkpoint {ckp_id: $ckp_id}) RETURN c"
        return await self.db.run_single(query, ckp_id=ckp_id)

    async def update_uri(self, ckp_id: str, new_uri: str) -> dict:
        """Update checkpoint URI.

        Args:
            ckp_id: Checkpoint ID.
            new_uri: New URI value.

        Returns:
            Updated checkpoint data.

        Raises:
            UIError: If checkpoint not found.
        """
        now = datetime.utcnow().isoformat()
        query = """
        MATCH (c:Checkpoint {ckp_id: $ckp_id})
        SET c.uri = $new_uri, c.updated_at = $updated_at
        RETURN c.ckp_id as ckp_id, c.uri as uri
        """
        result = await self.db.run_single(query, ckp_id=ckp_id, new_uri=new_uri, updated_at=now)
        if not result:
            raise UIError("Checkpoint not found")
        return dict(result)

    async def set_usable(self, ckp_id: str, is_usable: bool) -> dict:
        """Toggle checkpoint usability flag.

        Args:
            ckp_id: Checkpoint ID.
            is_usable: New usability state.

        Returns:
            Updated checkpoint data.

        Raises:
            UIError: If checkpoint not found.
        """
        now = datetime.utcnow().isoformat()
        query = """
        MATCH (c:Checkpoint {ckp_id: $ckp_id})
        SET c.is_usable = $is_usable, c.updated_at = $updated_at
        RETURN c.ckp_id as ckp_id, c.is_usable as is_usable
        """
        result = await self.db.run_single(query, ckp_id=ckp_id, is_usable=is_usable, updated_at=now)
        if not result:
            raise UIError("Checkpoint not found")
        return dict(result)

    async def get_dependencies(self, ckp_id: str) -> list[dict]:
        """Get experiments that STARTED_FROM this checkpoint.

        Args:
            ckp_id: Checkpoint ID.

        Returns:
            List of dependent experiment records.
        """
        query = """
        MATCH (e:Experiment)-[:STARTED_FROM]->(c:Checkpoint {ckp_id: $ckp_id})
        RETURN e.exp_id as exp_id, e.status as status, e.description as description
        """
        return await self.db.run_list(query, ckp_id=ckp_id)
