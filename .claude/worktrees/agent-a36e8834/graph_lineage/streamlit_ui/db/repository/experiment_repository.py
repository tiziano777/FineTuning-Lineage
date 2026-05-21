"""Repository for Experiment entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class ExperimentRepository:
    """Data access layer for Experiment entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client

    async def create(
        self,
        exp_id: str,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> dict:
        """Create a new experiment.

        Args:
            exp_id: Unique experiment ID.
            model_id: Associated Model ID.
            status: Experiment status.
            description: Experiment description.

        Returns:
            Created experiment data.
        """
        now = datetime.utcnow().isoformat()

        query = """
        CREATE (e:Experiment {
            id: $id,
            exp_id: $exp_id,
            model_id: $model_id,
            status: $status,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at,
            usable: true
        })
        RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=exp_id,
            exp_id=exp_id,
            model_id=model_id,
            status=status,
            description=description,
            created_at=now,
            updated_at=now,
        )

        if not result:
            raise UIError("Failed to create experiment in Neo4j")

        logger.info(f"Experiment created: id={exp_id}, model_id={model_id}")
        return result

    async def create_experiment(
        self,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> dict:
        """Create a new experiment (generates UUID automatically).

        Args:
            model_id: Associated Model ID.
            status: Experiment status (PENDING, RUNNING, COMPLETED, FAILED).
            description: Experiment description.

        Returns:
            Created experiment data.
        """
        import uuid
        exp_id = str(uuid.uuid4())
        return await self.create(
            exp_id=exp_id,
            model_id=model_id,
            status=status,
            description=description,
        )

    async def get_by_id(self, exp_id: str) -> Optional[dict]:
        """Get experiment by ID.

        Args:
            exp_id: Experiment ID.

        Returns:
            Experiment data or None if not found.
        """
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(query, id=exp_id)
        return result

    async def get_experiment(self, exp_id: str) -> Optional[dict]:
        """Alias for get_by_id for manager compatibility."""
        return await self.get_by_id(exp_id)

    async def list_all(self, status: Optional[str] = None) -> list[dict]:
        """List experiments optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            List of experiment dictionaries.
        """
        if status:
            query = """
            MATCH (e:Experiment {status: $status})
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at
            LIMIT 100
            """
            results = await self.db.run_list(query, status=status)
        else:
            query = """
            MATCH (e:Experiment)
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at
            LIMIT 100
            """
            results = await self.db.run_list(query)

        return results

    async def list_experiments(self, status: Optional[str] = None) -> list[dict]:
        """Alias for list_all for manager compatibility."""
        return await self.list_all(status=status)

    async def update(
        self,
        exp_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> dict:
        """Update experiment fields.

        Args:
            exp_id: Experiment ID.
            status: New status.
            description: New description.
            exit_status: Exit status.
            exit_msg: Exit message.

        Returns:
            Updated experiment data.
        """
        now = datetime.utcnow().isoformat()
        params = {"id": exp_id, "updated_at": now}

        # Build parameterized query based on which fields are provided
        if status is not None and description is not None and exit_status is not None and exit_msg is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description,
                e.exit_status = $exit_status, e.exit_msg = $exit_msg,
                e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description, "exit_status": exit_status, "exit_msg": exit_msg})
        elif status is not None and description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description})
        elif status is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["status"] = status
        elif description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["description"] = description
        else:
            query = """
            MATCH (e:Experiment {id: $id})
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """

        result = await self.db.run_single(query, **params)

        if not result:
            raise UIError(f"Experiment {exp_id} not found")

        logger.info(f"Experiment updated: id={exp_id}")
        return result

    async def update_experiment(
        self,
        exp_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> dict:
        """Alias for update for manager compatibility."""
        return await self.update(
            exp_id=exp_id,
            status=status,
            description=description,
            exit_status=exit_status,
            exit_msg=exit_msg,
        )

    async def delete(self, exp_id: str) -> None:
        """Delete experiment with constraint checking.

        Args:
            exp_id: Experiment ID to delete.

        Raises:
            UIError: If experiment not found, has generated checkpoints,
                     or has derived/branched experiments.
        """
        existing = await self.get_by_id(exp_id)
        if not existing:
            raise UIError(f"Experiment '{exp_id}' not found")

        # Check if experiment can be deleted
        if not await self.is_deletable(exp_id):
            raise UIError(
                f"Cannot delete experiment '{exp_id}': it has produced checkpoints "
                "or has derived/branched experiments. "
                "Remove dependent experiments/checkpoints first."
            )

        try:
            query = "MATCH (e:Experiment {id: $id}) DETACH DELETE e"
            await self.db.run(query, id=exp_id)
            logger.warning(f"Experiment deleted: id={exp_id}")
        except Exception as e:
            logger.error(f"Experiment deletion failed: {exp_id}", exc_info=True)
            raise UIError(f"Failed to delete experiment: {str(e)}")

    async def delete_experiment(self, exp_id: str) -> None:
        """Alias for delete for manager compatibility."""
        await self.delete(exp_id)

    async def is_deletable(self, exp_id: str) -> bool:
        """Check if experiment can be deleted.

        Experiment cannot be deleted if:
        - It has outgoing PRODUCED relationships (generated checkpoints)
        - It has outgoing DERIVED_FROM relationships (has derived/branched experiments)
        - It has outgoing STARTED_FROM relationships (physical branching from checkpoints)
        - It has outgoing RETRY_OF relationships (experiment is base for retries)

        Args:
            exp_id: Experiment ID to check.

        Returns:
            True if experiment has no blocking outgoing relationships, False otherwise.
        """
        existing = await self.get_by_id(exp_id)
        if not existing:
            return True

        # Query for blocking outgoing relationships
        query = """
        MATCH (e:Experiment {id: $id})
        OPTIONAL MATCH (e)-[:PRODUCED]->(cp:Checkpoint)
        OPTIONAL MATCH (e)-[:DERIVED_FROM]->(e2:Experiment)
        OPTIONAL MATCH (e)-[:STARTED_FROM]->(cp2:Checkpoint)
        OPTIONAL MATCH (e)-[:RETRY_OF]->(e3:Experiment)
        RETURN COUNT(DISTINCT cp) as produced_count,
               COUNT(DISTINCT e2) as derived_count,
               COUNT(DISTINCT cp2) as started_from_count,
               COUNT(DISTINCT e3) as retry_count
        """
        result = await self.db.run_single(query, id=exp_id)
        if result:
            produced_count = result.get("produced_count", 0)
            derived_count = result.get("derived_count", 0)
            started_from_count = result.get("started_from_count", 0)
            retry_count = result.get("retry_count", 0)
            return (
                produced_count == 0
                and derived_count == 0
                and started_from_count == 0
                and retry_count == 0
            )
        return True

    async def count_dependencies(self, exp_id: str) -> int:
        """Count checkpoints for this experiment.

        Args:
            exp_id: Experiment ID.

        Returns:
            Number of dependent checkpoints.
        """
        query = """
        MATCH (e:Experiment {id: $id})-[r:HAS_CHECKPOINT]->(cp)
        RETURN count(r) as dep_count
        """

        result = await self.db.run_single(query, id=exp_id)
        return result["dep_count"] if result else 0

    async def check_experiment_dependencies(self, exp_id: str) -> int:
        """Alias for count_dependencies for manager compatibility."""
        return await self.count_dependencies(exp_id)

    async def list_rich(self, status_filter: str = None, search: str = None) -> list[dict]:
        """List experiments with USES_MODEL, USES_RECIPE, USES_TECHNIQUE relationships and checkpoint count."""
        query = """
        MATCH (e:Experiment)
        OPTIONAL MATCH (e)-[:USES_MODEL]->(m:Model)
        OPTIONAL MATCH (e)-[:USES_RECIPE]->(r:Recipe)
        OPTIONAL MATCH (e)-[:USES_TECHNIQUE]->(c:Component)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
        WITH e, m, r, c, COUNT(ckp) as ckp_count
        RETURN e.exp_id as exp_id, e.status as status, e.description as description,
               e.usable as usable, e.config_hash as config_hash, e.created_at as created_at,
               e.notes as notes, m.model_name as model_name, r.name as recipe_name,
               c.technique_code as technique_code, c.framework_code as framework_code,
               ckp_count
        ORDER BY e.created_at DESC
        LIMIT 100
        """
        return await self.db.run_list(query)

    async def update_metadata(self, exp_id: str, description: str = None, notes: str = None) -> dict:
        """Update only description and notes fields (metadata edit)."""
        sets = []
        params = {"exp_id": exp_id, "updated_at": datetime.utcnow().isoformat()}
        if description is not None:
            sets.append("e.description = $description")
            params["description"] = description
        if notes is not None:
            sets.append("e.notes = $notes")
            params["notes"] = notes
        if not sets:
            raise UIError("No fields to update")
        query = f"MATCH (e:Experiment {{exp_id: $exp_id}}) SET {', '.join(sets)}, e.updated_at = $updated_at RETURN e.exp_id as exp_id"
        result = await self.db.run_single(query, **params)
        if not result:
            raise UIError("Experiment not found")
        return dict(result)
