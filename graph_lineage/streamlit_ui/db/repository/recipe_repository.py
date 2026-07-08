"""Repository for Recipe entity - Neo4j data access layer."""

from __future__ import annotations

import json
import logging
from typing import Optional

import yaml
from pydantic import ValidationError

from graph_lineage.data_classes.neo4j.nodes.recipe import Recipe
from graph_lineage.streamlit_ui.utils.errors import UIError, DuplicateRecipeError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class RecipeRepository:
    """Data access layer per l'entità Recipe.

    Principi:
    - Ogni operazione di scrittura (create/update/upsert) riceve in input
      un'istanza `Recipe` già validata. Grazie a `model_config = ConfigDict(extra="allow")`
      qualunque campo custom attaccato all'oggetto viene persistito e riletto
      automaticamente, senza bisogno di isolarlo a mano.
    - Ogni query di lettura ritorna il nodo intero (`r{.*}`) invece di un elenco
      di campi hardcoded: i campi custom non vengono mai persi in lettura.
    """

    def __init__(self, db_client: AsyncNeo4jClient):
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_recipe(row) -> Recipe:
        """Converte una riga Neo4j (colonna singola 'recipe', mappa completa) in Recipe."""
        data = dict(row["recipe"])
        return Recipe(**data)

    @staticmethod
    def _recipe_to_props(recipe: Recipe, *, exclude: set[str] | None = None) -> dict:
        """Appiattisce un Recipe (campi core + eventuali campi custom) in un dict
        di proprietà salvabili su Neo4j.
        
        Nel processo:
        - `entries` viene serializzato come stringa JSON (Neo4j non supporta liste di mappe)
        - Ogni entry contiene `system_prompt` come Dict[str, str] ({prompt_name: content})
        - Tutti i campi custom (extra='allow') vengono preservati automaticamente
        """
        exclude_fields = (exclude or set()) | {"entries"}
        props = recipe.model_dump(mode="json", exclude_none=True, exclude=exclude_fields)
        props["entries"] = json.dumps(
            [entry.model_dump(mode="json", exclude_none=True) for entry in recipe.entries]
        )
        return props

    @staticmethod
    def _recipe_from_yaml(
        yaml_content: str,
        description: str = "",
        filename: Optional[str] = None,
    ) -> Recipe:
        """Parsa un contenuto YAML in un'istanza Recipe validata.
        
        Atteso formato YAML con:
        - entries: lista di distribuzioni
        - Ogni entry può contenere system_prompt: Dict[str, str] (nuovo formato)
        
        Qualsiasi campo non definito esplicitamente su Recipe/RecipeEntry resta
        come campo custom (extra='allow'), senza bisogno di gestione manuale.
        Questo assicura massima estendibilità per campi futuri.
        """
        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise UIError("YAML must contain a dictionary")

            if "recipe" in data and isinstance(data["recipe"], dict):
                data = data["recipe"]

            if "entries" not in data or not isinstance(data.get("entries"), list):
                raise UIError("YAML must contain top-level 'entries' list of distribution metadata")

            if description and description.strip():
                data["description"] = description

            recipe = Recipe(**data)
        except UIError:
            raise
        except ValidationError as e:
            raise UIError(f"Invalid recipe data: {str(e)}")
        except Exception as e:
            raise UIError(f"Failed to parse YAML: {str(e)}")

        if recipe.name is None:
            if not filename:
                raise UIError(
                    "Recipe name required: provide 'name' field in YAML or upload file with valid filename"
                )
            recipe.ensure_name(filename)

        return recipe

    async def _list(self, query: str, params: dict | None = None) -> list[Recipe]:
        try:
            result = await self.db.query(query, params or {})
            recipes = []
            for row in result or []:
                try:
                    recipes.append(self._row_to_recipe(row))
                except ValidationError as e:
                    logger.warning(f"Skipping invalid recipe row due to: {e}")
            logger.debug(f"Found {len(recipes)} recipes")
            return recipes
        except Exception as e:
            logger.error(f"Failed to list recipes: {e}")
            raise UIError(f"Failed to list recipes: {str(e)}")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, recipe_id: str) -> Optional[Recipe]:
        """Recupera una recipe per id, inclusi eventuali campi custom."""
        logger.debug(f"Querying recipe by id: {recipe_id}")
        try:
            query = "MATCH (r:Recipe {id: $id}) RETURN r{.*} as recipe"
            result = await self.db.query(query, {"id": recipe_id})
            if not result:
                return None
            try:
                return self._row_to_recipe(result[0])
            except ValidationError as e:
                logger.error(f"Invalid recipe data for id '{recipe_id}': {e}")
                raise UIError(f"Invalid recipe data: {str(e)}")
        except UIError:
            raise
        except Exception as e:
            logger.error(f"Failed to get recipe by id: {e}")
            raise UIError(f"Failed to retrieve recipe: {str(e)}")

    async def get_by_name(self, name: str) -> Optional[Recipe]:
        """Recupera una recipe per nome, inclusi eventuali campi custom."""
        logger.debug(f"Querying recipe by name: {name}")
        try:
            query = "MATCH (r:Recipe {name: $name}) RETURN r{.*} as recipe"
            result = await self.db.query(query, {"name": name})
            if not result:
                return None
            try:
                recipe = self._row_to_recipe(result[0])
                logger.debug(f"Recipe found: {name} (entry_count={len(recipe.entries)})")
                return recipe
            except ValidationError as e:
                logger.error(f"Invalid recipe data for name '{name}': {e}")
                raise UIError(f"Invalid recipe data: {str(e)}")
        except UIError:
            raise
        except Exception as e:
            logger.error(f"Failed to get recipe by name: {e}")
            raise UIError(f"Failed to retrieve recipe: {str(e)}")

    async def list_all(self) -> list[Recipe]:
        return await self._list(
            "MATCH (r:Recipe) RETURN r{.*} as recipe ORDER BY r.created_at DESC"
        )

    async def list_with_limit(self, limit: int = 20) -> list[Recipe]:
        return await self._list(
            "MATCH (r:Recipe) RETURN r{.*} as recipe ORDER BY r.created_at DESC LIMIT $limit",
            {"limit": limit},
        )

    async def search(self, query_str: str) -> list[Recipe]:
        return await self._list(
            """
            MATCH (r:Recipe)
            WHERE toLower(r.name) CONTAINS toLower($query)
            RETURN r{.*} as recipe
            ORDER BY r.created_at DESC
            """,
            {"query": query_str},
        )

    # ------------------------------------------------------------------
    # Write — sempre a partire da un'istanza Recipe
    # ------------------------------------------------------------------

    async def create_from_yaml(
        self,
        yaml_content: str,
        description: str = "",
        filename: Optional[str] = None,
    ) -> Recipe:
        """Parsa uno YAML in Recipe e la crea. Solleva DuplicateRecipeError in conflitto."""
        recipe = self._recipe_from_yaml(yaml_content, description=description, filename=filename)
        logger.info(
            "Creating recipe from YAML: recipe_id=%s name=%s entry_count=%d",
            recipe.id, recipe.name, len(recipe.entries),
        )
        return await self.create(recipe)

    async def save_from_yaml(
        self,
        yaml_content: str,
        description: str = "",
        filename: Optional[str] = None,
        overwrite: bool = False,
    ) -> Recipe:
        """Parsa uno YAML e lo persiste.

        Se `overwrite=True`, una recipe esistente con lo stesso id viene
        sostituita sul posto via upsert (preservando il suo `created_at`
        originale); altrimenti si comporta come `create_from_yaml`.
        """
        recipe = self._recipe_from_yaml(yaml_content, description=description, filename=filename)
        if overwrite:
            return await self.upsert(recipe)
        return await self.create(recipe)

    async def create(self, recipe: Recipe) -> Recipe:
        """Crea un nuovo nodo Recipe. Tutti i campi (core + custom) vengono persistiti."""
        logger.debug("Checking recipe uniqueness: id=%s name=%s", recipe.id, recipe.name)
        if await self.get_by_id(recipe.id):
            logger.warning("Recipe id already exists: %s", recipe.id)
            raise DuplicateRecipeError(recipe.id, recovery_suggestions=[f"{recipe.id}_dup"])

        if recipe.name:
            existing_by_name = await self.get_by_name(recipe.name)
            if existing_by_name and existing_by_name.id != recipe.id:
                logger.warning("Recipe name already exists: %s", recipe.name)
                raise DuplicateRecipeError(recipe.name, recovery_suggestions=[f"{recipe.name}_v1"])

        try:
            logger.info("Inserting recipe: name=%s, entry_count=%d", recipe.name, len(recipe.entries))
            props = self._recipe_to_props(recipe)

            query = """
            CREATE (r:Recipe)
            SET r = $props
            SET r.created_at = datetime()
            SET r.updated_at = datetime()
            RETURN r{.*} as recipe
            """
            result = await self.db.query(query, {"props": props})
            if not result:
                raise UIError("Failed to create recipe")

            created = self._row_to_recipe(result[0])
            logger.info(f"Recipe inserted successfully: name={created.name}")
            return created
        except Exception as e:
            if isinstance(e, (UIError, DuplicateRecipeError)):
                raise
            logger.error(f"Recipe insertion failed: {recipe.name}", exc_info=True)
            raise UIError(f"Failed to create recipe: {str(e)}")

    async def update(self, recipe: Recipe) -> Recipe:
        """Aggiorna una recipe esistente, individuata da `recipe.id`.

        Ogni campo impostato su `recipe` (core + custom) sovrascrive il valore
        salvato, tranne `created_at` (sempre preservato) e `updated_at`
        (sempre rigenerato).
        """
        if not recipe.id:
            raise UIError("Recipe id is required to update a recipe")

        existing = await self.get_by_id(recipe.id)
        if not existing:
            raise UIError("Recipe not found")

        if recipe.name and recipe.name != existing.name:
            conflict = await self.get_by_name(recipe.name)
            if conflict and conflict.id != recipe.id:
                raise UIError(f"Recipe '{recipe.name}' already exists")

        try:
            logger.info("Updating recipe: recipe_id=%s", recipe.id)
            props = self._recipe_to_props(recipe, exclude={"created_at", "id"})

            query = """
            MATCH (r:Recipe {id: $id})
            SET r += $props
            SET r.updated_at = datetime()
            RETURN r{.*} as recipe
            """
            result = await self.db.query(query, {"id": recipe.id, "props": props})
            if not result:
                raise UIError("Failed to update recipe")

            updated = self._row_to_recipe(result[0])
            logger.info(f"Recipe updated: {updated.id}")
            return updated
        except Exception as e:
            if isinstance(e, UIError):
                raise
            logger.error(f"Recipe update failed: {recipe.id}", exc_info=True)
            raise UIError(f"Failed to update recipe: {str(e)}")

    async def upsert(self, recipe: Recipe) -> Recipe:
        """Crea o aggiorna una recipe, individuata da `recipe.id`.

        Alla creazione: tutti i campi vengono impostati, `created_at`/`updated_at`
        inizializzati. Al match: tutti i campi vengono sovrascritti (custom
        inclusi), `created_at` è preservato, `updated_at` rigenerato.
        """
        if not recipe.id:
            raise UIError("Recipe id is required to upsert a recipe")

        if recipe.name:
            existing_by_name = await self.get_by_name(recipe.name)
            if existing_by_name and existing_by_name.id != recipe.id:
                raise UIError(f"Recipe '{recipe.name}' already exists with a different id")

        try:
            logger.info("Upserting recipe: recipe_id=%s name=%s", recipe.id, recipe.name)
            create_props = self._recipe_to_props(recipe)
            match_props = self._recipe_to_props(recipe, exclude={"created_at", "id"})

            query = """
            MERGE (r:Recipe {id: $id})
            ON CREATE SET r = $create_props, r.created_at = datetime(), r.updated_at = datetime()
            ON MATCH SET r += $match_props, r.updated_at = datetime()
            RETURN r{.*} as recipe
            """
            result = await self.db.query(query, {
                "id": recipe.id,
                "create_props": create_props,
                "match_props": match_props,
            })
            if not result:
                raise UIError("Failed to upsert recipe")

            saved = self._row_to_recipe(result[0])
            logger.info(f"Recipe upserted: id={saved.id} name={saved.name}")
            return saved
        except Exception as e:
            if isinstance(e, UIError):
                raise
            logger.error(f"Recipe upsert failed: {recipe.id}", exc_info=True)
            raise UIError(f"Failed to upsert recipe: {str(e)}")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def is_deletable(self, recipe_id: str) -> bool:
        """Verifica se una recipe può essere eliminata."""
        existing = await self.get_by_id(recipe_id)
        if not existing:
            return True
        if existing.name:
            return await self.constraints.is_recipe_deletable(existing.name)
        return True

    async def delete(self, recipe_id: str) -> None:
        """Elimina una recipe per id."""
        existing = await self.get_by_id(recipe_id)
        if not existing:
            raise UIError(f"Recipe '{recipe_id}' not found")

        if not await self.is_deletable(recipe_id):
            raise UIError(
                f"Cannot delete recipe '{existing.name}': it's used by one or more experiments. "
                "Remove experiments first before deleting the recipe."
            )

        try:
            logger.info("Deleting recipe: recipe_id=%s", recipe_id)
            await self.db.query("MATCH (r:Recipe {id: $id}) DELETE r", {"id": recipe_id})
            logger.info("Recipe deleted: recipe_id=%s", recipe_id)
        except Exception as e:
            logger.error(f"Recipe deletion failed: {recipe_id}", exc_info=True)
            raise UIError(f"Failed to delete recipe: {str(e)}")
