"""Entity constraints and deletability checks."""

import logging

from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient
from graph_lineage.streamlit_ui.utils.errors import UIError

logger = logging.getLogger(__name__)


class EntityConstraints:
    """Validates entity constraints (e.g., deletability) via Neo4j queries."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize with Neo4j client.

        Args:
            db_client: AsyncNeo4jClient for database queries.
        """
        self.db = db_client

    async def is_recipe_deletable(self, recipe_name: str) -> bool:
        """Check if recipe can be deleted (no related experiments).

        A recipe can be deleted only if no Experiment nodes reference it
        via -[:BASED_ON]-> relationship.

        Args:
            recipe_name: Recipe name to check.

        Returns:
            True if recipe has no related experiments, False otherwise.
        """
        try:
            query = """
            MATCH (r:Recipe {name: $name})
            OPTIONAL MATCH (r)<-[:BASED_ON]-(e:Experiment)
            RETURN COUNT(e) as experiment_count
            """
            result = await self.db.query(query, {"name": recipe_name})
            if result:
                count = result[0].get("experiment_count", 0)
                logger.debug(f"Recipe '{recipe_name}' has {count} related experiments")
                return count == 0
            return True  # Recipe doesn't exist, considered deletable
        except Exception as e:
            logger.error(f"Failed to check recipe deletability: {e}")
            raise UIError(f"Failed to check if recipe can be deleted: {str(e)}")

    async def is_model_deletable(self, model_name: str) -> bool:
        """Check if model can be deleted (no related experiments).

        A model can be deleted only if no Experiment nodes reference it
        via -[:SELECTED_FOR]-> relationship.

        Args:
            model_name: Model name to check.

        Returns:
            True if model has no related experiments, False otherwise.
        """
        try:
            query = """
            MATCH (m:Model {name: $name})
            OPTIONAL MATCH (m)<-[:SELECTED_FOR]-(e:Experiment)
            RETURN COUNT(e) as experiment_count
            """
            result = await self.db.query(query, {"name": model_name})
            if result:
                count = result[0].get("experiment_count", 0)
                logger.debug(f"Model '{model_name}' has {count} related experiments")
                return count == 0
            return True  # Model doesn't exist, considered deletable
        except Exception as e:
            logger.error(f"Failed to check model deletability: {e}")
            raise UIError(f"Failed to check if model can be deleted: {str(e)}")

    async def is_component_deletable(self, component_name: str) -> bool:
        """Check if component can be deleted (no related experiments).

        A component can be deleted only if no Experiment nodes reference it
        via -[:USED_FOR]-> relationship.

        Args:
            component_name: Component name to check.

        Returns:
            True if component has no related experiments, False otherwise.
        """
        try:
            query = """
            MATCH (c:Component {name: $name})
            OPTIONAL MATCH (c)<-[:USED_FOR]-(e:Experiment)
            RETURN COUNT(e) as experiment_count
            """
            result = await self.db.query(query, {"name": component_name})
            if result:
                count = result[0].get("experiment_count", 0)
                logger.debug(f"Component '{component_name}' has {count} related experiments")
                return count == 0
            return True  # Component doesn't exist, considered deletable
        except Exception as e:
            logger.error(f"Failed to check component deletability: {e}")
            raise UIError(f"Failed to check if component can be deleted: {str(e)}")
