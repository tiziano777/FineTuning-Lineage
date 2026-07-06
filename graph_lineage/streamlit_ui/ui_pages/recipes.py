"""Recipe management page."""

from __future__ import annotations

import logging
import streamlit as st
from graph_lineage.data_classes.neo4j.nodes.recipe import Recipe

from graph_lineage.streamlit_ui.db.repository.recipe_repository import RecipeRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError, DuplicateRecipeError
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.recipe_validation import validate_recipe_yaml
from graph_lineage.streamlit_ui.utils.scope_enum import ScopeEnum
from graph_lineage.streamlit_ui.utils.task_enum import TaskEnum

logger = logging.getLogger(__name__)

# Async helper functions for recipe operations
async def create_recipe_async(yaml_content: str, description: str = "") -> Recipe:
    """Create recipe asynchronously from YAML content."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.create_from_yaml(yaml_content=yaml_content, description=description)

async def search_recipes_async(query: str) -> list[Recipe]:
    """Search recipes asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.search(query)

async def list_recipes_async(limit: int = 20) -> list[Recipe]:
    """List recipes asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.list_with_limit(limit=limit)

async def update_recipe_async(recipe_id: str, new_name: str | None = None, description: str = "", scope: str | None = None, tasks: list[str] | None = None, tags: list[str] | None = None) -> Recipe:
    """Update recipe asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.update(recipe_id=recipe_id, new_name=new_name, description=description, scope=scope, tasks=tasks, tags=tags)  # repo.update internally maps to id

async def delete_recipe_async(recipe_id: str) -> None:
    """Delete recipe asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    await repo.delete(recipe_id=recipe_id)

async def is_recipe_deletable_async(recipe_id: str) -> bool:
    """Check if recipe can be deleted asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.is_deletable(recipe_id=recipe_id)

async def get_recipe_by_id_async(recipe_id: str) -> Recipe | None:
    """Check if recipe exists by ID."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.get_by_id(recipe_id)

def run() -> None:
    """Run recipe management page."""
    st.title("Recipe Management")

    tab1, tab2 = st.tabs(["Upload", "Browse"])

    with tab1:
        st.subheader("Upload YAML Recipe")

        uploaded_file = st.file_uploader("Upload YAML recipe", type=["yaml", "yml"])

        if uploaded_file:
            MAX_FILE_SIZE_MB = 10
            if uploaded_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                st.error(f"File too large. Max {MAX_FILE_SIZE_MB}MB allowed.")
            else:
                yaml_content = uploaded_file.read().decode("utf-8")
                logger.debug("Uploaded file read: name=%s size=%d", uploaded_file.name, len(yaml_content))
                is_valid, config, errors = validate_recipe_yaml(yaml_content)

                if is_valid:
                    st.success("✓ Recipe validation passed")
                    # Display entry count on successful validation
                    entries_count = len(config.entries) if hasattr(config, 'entries') and config.entries else 0
                    yaml_name = getattr(config, 'name', None)
                    yaml_id = getattr(config, 'id', None)
                    yaml_description = getattr(config, 'description', None)
                    st.info(f"**Name:** {yaml_name or 'N/A'} | **Recipe ID:** {yaml_id or 'N/A'} | **Description:** {yaml_description or 'N/A'} | **Entries:** {entries_count}")
                    logger.info("Validation passed for %s: detected_entries=%d", uploaded_file.name, entries_count)
                    try:
                        keys = list(config.entries.keys()) if hasattr(config, 'entries') and config.entries else []
                        logger.debug("Validated config sample keys=%s", keys[:5])
                    except Exception:
                        logger.exception("Failed to inspect config entries after validation")

                    # Check if recipe with this ID already exists
                    existing_recipe = None
                    if yaml_id:
                        existing_recipe = run_async(get_recipe_by_id_async(str(yaml_id)))

                    if existing_recipe:
                        st.warning(f"⚠️ A recipe with ID `{yaml_id}` already exists: **{existing_recipe.name}**")
                        if st.button("Confirm Overwrite", key="confirm_overwrite_recipe"):
                            st.session_state["overwrite_recipe_confirmed"] = True

                    # Determine if we can proceed with save
                    can_save = not existing_recipe or st.session_state.get("overwrite_recipe_confirmed", False)

                    if can_save:
                        if st.button("Save Recipe", disabled=st.session_state.get("saving_recipe", False)):
                            st.session_state.saving_recipe = True

                            try:
                                # If overwriting, delete existing first
                                if existing_recipe:
                                    logger.info("Overwriting existing recipe: id=%s", yaml_id)
                                    run_async(delete_recipe_async(recipe_id=str(yaml_id)))

                                logger.info("Creating recipe from upload: filename=%s", uploaded_file.name)
                                logger.info(f"[INFO] YAML content: {yaml_content}")
                                result = run_async(
                                    create_recipe_async(
                                        yaml_content=yaml_content,
                                        description=yaml_description or ""
                                    )
                                )
                                logger.debug("Create recipe result: %s", result)
                                # Entry count confirmation
                                entry_count = len(result.get('entries', {})) if result.get('entries') else 0
                                action = "overwritten" if existing_recipe else "created"
                                st.success(f"✓ Recipe '{result.get('name')}' {action} successfully! ({entry_count} entries)")
                                st.toast("Recipe saved!", icon="✅")
                                # Reset overwrite state
                                st.session_state.pop("overwrite_recipe_confirmed", None)

                            except DuplicateRecipeError as e:
                                st.error(f"Error: {e.user_message}")
                                st.caption(e.details)
                                st.info("💡 To resolve: Rename the YAML file (e.g., 'my_recipe_v2.yaml') and re-upload.")

                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
                                st.caption(e.details)

                            finally:
                                st.session_state.saving_recipe = False
                else:
                    st.error("✗ Recipe validation failed")
                    for error in errors:
                        st.error(f"  • {error}")

    with tab2:
        st.subheader("Browse & Manage Recipes")

        search_query = st.text_input("Search by name", value="", key="search_recipes")

        try:
            if search_query.strip():
                recipes = run_async(search_recipes_async(search_query))
                st.caption(f"Found {len(recipes)} recipe(s)")
            else:
                recipes = run_async(list_recipes_async(limit=20))

            if recipes:
                for recipe in recipes:
                    key_suffix = recipe.id if recipe.id is not None else recipe.name
                    display_name = recipe.name or recipe.id
                    with st.expander(f"📋 {display_name} - {key_suffix}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"Recipe ID: {recipe.id or 'N/A'}")
                            st.write(f"**Description:** {recipe.description or 'N/A'}")
                            
                            st.write(f"**Scope:** {recipe.scope or 'N/A'}")
                            st.write(f"**Tasks:** {', '.join(recipe.tasks or [])}")
                            st.write(f"**Tags:** {', '.join(recipe.tags or [])}")
                            st.write(f"**Derived from:** {recipe.derived_from or 'N/A'}")

                            st.caption(f"Created: {recipe.created_at or 'N/A'}")
                            st.caption(f"Updated: {recipe.updated_at or 'N/A'}")

                            # Display recipe entries — show full metadata per RecipeEntry
                            entries = recipe.entries
                            if entries and isinstance(entries, dict):
                                st.divider()
                                st.subheader("📊 Dataset Entries")
                                for dist_uri, entry in entries.items():
                                    if isinstance(entry, dict):
                                        st.markdown(f"**URI:** `{dist_uri}`")
                                        cols = st.columns([2, 2])
                                        left, right = cols
                                        with left:
                                            st.write(f"**dist_id:** {entry.dist_id or 'N/A'}")
                                            st.write(f"**dist_name:** {entry.dist_name or 'N/A'}")
                                            st.write(f"**chat_type:** {entry.chat_type or 'N/A'}")
                                            st.write(f"**replica:** {entry.replica or 'N/A'}")
                                            st.write(f"**samples:** {entry.samples or 'N/A'}")
                                        with right:
                                            st.write(f"**tokens:** {entry.tokens or 'N/A'}")
                                            st.write(f"**words:** {entry.words or 'N/A'}")
                                            st.write(f"**system_prompt_name:** {entry.system_prompt_name or []}")
                                            st.write(f"**system_prompt:** {[e[:150] for e in entry.system_prompt or []]}")
                                        # schema_template and validation_error may be large structures
                                        if entry.schema_template:
                                            st.caption("schema_template:")
                                            st.json(entry.schema_template)
                                        if entry.validation_error:
                                            st.error(f"Validation error: {entry.validation_error}")
                                        st.markdown("---")
                            else:
                                st.info("No entries in this recipe")

                        with col2:
                            col_edit, col_delete = st.columns(2)
                            with col_edit:
                                if st.button("✏️ Edit", key=f"edit_{key_suffix}"):
                                    st.session_state[f"edit_recipe_{key_suffix}"] = True

                            with col_delete:
                                # Check if recipe can be deleted
                                can_delete = run_async(is_recipe_deletable_async(recipe.id or recipe.name))
                                if st.button(
                                    "🗑️ Delete",
                                    key=f"delete_{key_suffix}",
                                    disabled=not can_delete,
                                    help="Delete is disabled if recipe is used by experiments"
                                ):
                                    st.session_state[f"confirm_delete_{key_suffix}"] = True

                        if st.session_state.get(f"edit_recipe_{key_suffix}", False):
                            st.divider()
                            st.subheader("Edit Recipe")
                            # Allow editing name, description, scope, tasks, and tags
                            new_name_input = st.text_input("Recipe Name", value=recipe.name or '', key=f"new_name_{key_suffix}")
                            new_desc = st.text_area("Description", value=recipe.description or '', key=f"new_desc_{key_suffix}")

                            # Scope multiselect
                            current_scope = recipe.scope
                            selected_scope = st.selectbox(
                                "Scope",
                                options=[None] + ScopeEnum.values(),
                                index=0 if not current_scope else (ScopeEnum.values().index(current_scope) + 1) if current_scope in ScopeEnum.values() else 0,
                                key=f"scope_{key_suffix}"
                            )
                            new_scope = selected_scope if selected_scope else None

                            # Tasks multiselect
                            current_tasks = recipe.tasks or []
                            # Filter to only include valid enum values
                            valid_enum_values = TaskEnum.values()
                            filtered_tasks = [t for t in current_tasks if t in valid_enum_values]
                            selected_tasks = st.multiselect(
                                "Tasks",
                                options=valid_enum_values,
                                default=filtered_tasks,
                                key=f"tasks_{key_suffix}"
                            )

                            # Tags (free-form list)
                            current_tags = recipe.tags or []
                            tags_text = st.text_area(
                                "Tags (one per line)",
                                value='\n'.join(current_tags) if current_tags else '',
                                key=f"tags_{key_suffix}"
                            )
                            new_tags = [tag.strip() for tag in tags_text.split('\n') if tag.strip()]

                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                if st.button("Save Changes", key=f"save_edit_{key_suffix}"):
                                    try:
                                        result = run_async(
                                            update_recipe_async(
                                                recipe_id=recipe.id or recipe.name,
                                                new_name=new_name_input if new_name_input != recipe.name else None,
                                                description=new_desc,
                                                scope=new_scope,
                                                tasks=selected_tasks if selected_tasks else None,
                                                tags=new_tags if new_tags else None,
                                            )
                                        )
                                        st.success("✓ Recipe updated!")
                                        st.session_state[f"edit_recipe_{key_suffix}"] = False
                                        st.rerun()
                                    except UIError as e:
                                        msg = str(e)
                                        if "already exists" in msg or "exists" in msg:
                                            st.error(f"Name conflict: {msg}")
                                            st.info("Choose a different name and try again.")
                                        else:
                                            st.error(f"Error: {e}")

                            with col_cancel:
                                if st.button("Cancel", key=f"cancel_edit_{key_suffix}"):
                                    st.session_state[f"edit_recipe_{key_suffix}"] = False
                                    st.rerun()

                        if st.session_state.get(f"confirm_delete_{key_suffix}", False):
                            st.divider()
                            st.warning(f"⚠️ Are you sure you want to delete '{recipe.name or recipe.id}'?")
                            col_confirm, col_cancel = st.columns(2)

                            with col_confirm:
                                if st.button("Yes, delete", key=f"confirm_delete_yes_{key_suffix}", type="primary"):
                                    try:
                                        run_async(delete_recipe_async(recipe_id=recipe.id or recipe.name))
                                        st.success(f"✓ Recipe '{recipe.name or recipe.id}' deleted!")
                                        st.session_state[f"confirm_delete_{key_suffix}"] = False
                                        st.rerun()
                                    except UIError as e:
                                        st.error(f"Error: {e.user_message}")

                            with col_cancel:
                                if st.button("Cancel", key=f"cancel_delete_{key_suffix}"):
                                    st.session_state[f"confirm_delete_{key_suffix}"] = False
                                    st.rerun()
            else:
                st.info("No recipes found.")
        except UIError as e:
            st.error(f"Error: {e.user_message}")
            st.caption(e.details)
