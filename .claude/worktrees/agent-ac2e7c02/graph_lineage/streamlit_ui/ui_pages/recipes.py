"""Recipe management page."""

from __future__ import annotations

import asyncio

import logging
import streamlit as st

from graph_lineage.streamlit_ui.db.repository.recipe_repository import RecipeRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError, DuplicateRecipeError
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.recipe_validation import validate_recipe_yaml
from graph_lineage.streamlit_ui.utils.scope_enum import ScopeEnum
from graph_lineage.streamlit_ui.utils.task_enum import TaskEnum

logger = logging.getLogger(__name__)

# Async helper functions for recipe operations
async def create_recipe_async(yaml_content: str, description: str = "") -> dict:
    """Create recipe asynchronously from YAML content."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.create_from_yaml(yaml_content=yaml_content, description=description)


async def search_recipes_async(query: str) -> list[dict]:
    """Search recipes asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.search(query)


async def list_recipes_async(limit: int = 20) -> list[dict]:
    """List recipes asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.list_with_limit(limit=limit)


async def update_recipe_async(recipe_id: str, new_name: str | None = None, description: str = "", scope: str | None = None, tasks: list[str] | None = None, tags: list[str] | None = None) -> dict:
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


async def upsert_recipe_by_uri_async(
    uri: str, name: str, description: str = "",
    scope: str = "", tasks: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Upsert recipe by URI asynchronously."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.upsert_by_uri(
        uri=uri, name=name, description=description,
        scope=scope, tasks=tasks, tags=tags,
    )

def run() -> None:
    """Run recipe management page."""
    st.title("Recipe Management")

    tab1, tab2, tab3 = st.tabs(["Upload", "Upsert by URI", "Browse"])

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

                    if st.button("Save Recipe", disabled=st.session_state.get("saving_recipe", False)):
                        st.session_state.saving_recipe = True

                        try:
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
                            st.success(f"✓ Recipe '{result.get('name')}' created successfully! ({entry_count} entries)")
                            st.toast("Recipe saved!", icon="✅")

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
        st.subheader("Upsert Recipe by URI")
        st.info("Recipe will be created if the URI is new, or updated if a recipe with this URI already exists.")
        with st.form("upsert_recipe_form"):
            upsert_uri = st.text_input("Recipe URI", placeholder="hf://datasets/my-org/my-dataset")
            upsert_name = st.text_input("Recipe Name", placeholder="my_recipe")
            upsert_description = st.text_area("Description", value="")
            upsert_scope = st.text_input("Scope", value="", placeholder="sft")
            upsert_tasks_str = st.text_input("Tasks (comma-separated)", value="")
            upsert_tags_str = st.text_input("Tags (comma-separated)", value="")
            upsert_submitted = st.form_submit_button("Upload Recipe")

            if upsert_submitted:
                if not upsert_uri.strip():
                    st.error("URI is required")
                elif not upsert_name.strip():
                    st.error("Name is required")
                else:
                    try:
                        tasks_list = [t.strip() for t in upsert_tasks_str.split(",") if t.strip()] if upsert_tasks_str.strip() else None
                        tags_list = [t.strip() for t in upsert_tags_str.split(",") if t.strip()] if upsert_tags_str.strip() else None
                        result = run_async(
                            upsert_recipe_by_uri_async(
                                uri=upsert_uri,
                                name=upsert_name,
                                description=upsert_description,
                                scope=upsert_scope,
                                tasks=tasks_list,
                                tags=tags_list,
                            )
                        )
                        st.success(f"Recipe '{result.get('name')}' saved successfully!")
                        st.toast("Recipe saved!", icon="✅")
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in upsert_recipe_by_uri")

    with tab3:
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
                    key_suffix = recipe.get("id") if recipe.get("id") is not None else recipe.get("name")
                    display_name = recipe.get('name') or recipe.get('id')
                    with st.expander(f"📋 {display_name} - {key_suffix}", expanded=False):
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.write(f"Recipe ID: {recipe.get('id', 'N/A')}")
                            st.write(f"**Description:** {recipe.get('description', 'N/A')}")
                            
                            st.write(f"**Scope:** {recipe.get('scope', 'N/A')}")
                            st.write(f"**Tasks:** {', '.join(recipe.get('tasks', []))}")
                            st.write(f"**Tags:** {', '.join(recipe.get('tags', []))}")
                            st.write(f"**Derived from:** {recipe.get('derived_from', 'N/A')}")

                            st.caption(f"Created: {recipe.get('created_at', 'N/A')}")
                            st.caption(f"Updated: {recipe.get('updated_at', 'N/A')}")

                            # Display recipe entries — show full metadata per RecipeEntry
                            entries = recipe.get("entries")
                            if entries and isinstance(entries, dict):
                                st.divider()
                                st.subheader("📊 Dataset Entries")
                                for dist_uri, entry in entries.items():
                                    if isinstance(entry, dict):
                                        st.markdown(f"**URI:** `{dist_uri}`")
                                        cols = st.columns([2, 2])
                                        left, right = cols
                                        with left:
                                            st.write(f"**dist_id:** {entry.get('dist_id', 'N/A')}")
                                            st.write(f"**dist_name:** {entry.get('dist_name', 'N/A')}")
                                            st.write(f"**chat_type:** {entry.get('chat_type', 'N/A')}")
                                            st.write(f"**replica:** {entry.get('replica', 'N/A')}")
                                            st.write(f"**samples:** {entry.get('samples', 'N/A')}")
                                        with right:
                                            st.write(f"**tokens:** {entry.get('tokens', 'N/A')}")
                                            st.write(f"**words:** {entry.get('words', 'N/A')}")
                                            st.write(f"**system_prompt_name:** {entry.get('system_prompt_name', [])}")
                                            st.write(f"**system_prompt:** {[e[:150] for e in entry.get('system_prompt', [])]}")
                                        # schema_template and validation_error may be large structures
                                        if entry.get('schema_template'):
                                            st.caption("schema_template:")
                                            st.json(entry.get('schema_template'))
                                        if entry.get('validation_error'):
                                            st.error(f"Validation error: {entry.get('validation_error')}")
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
                                can_delete = run_async(is_recipe_deletable_async(recipe.get('id') or recipe.get('name')))
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
                            new_name_input = st.text_input("Recipe Name", value=recipe.get('name') or '', key=f"new_name_{key_suffix}")
                            new_desc = st.text_area("Description", value=recipe.get('description') or '', key=f"new_desc_{key_suffix}")

                            # Scope multiselect
                            current_scope = recipe.get('scope')
                            selected_scope = st.selectbox(
                                "Scope",
                                options=[None] + ScopeEnum.values(),
                                index=0 if not current_scope else (ScopeEnum.values().index(current_scope) + 1) if current_scope in ScopeEnum.values() else 0,
                                key=f"scope_{key_suffix}"
                            )
                            new_scope = selected_scope if selected_scope else None

                            # Tasks multiselect
                            current_tasks = recipe.get('tasks') or []
                            selected_tasks = st.multiselect(
                                "Tasks",
                                options=TaskEnum.values(),
                                default=current_tasks if current_tasks else [],
                                key=f"tasks_{key_suffix}"
                            )

                            # Tags (free-form list)
                            current_tags = recipe.get('tags') or []
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
                                                recipe_id=recipe.get('id') or recipe.get('name'),
                                                new_name=new_name_input if new_name_input != recipe.get('name') else None,
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
                            st.warning(f"⚠️ Are you sure you want to delete '{recipe.get('name') or recipe.get('id')}'?")
                            col_confirm, col_cancel = st.columns(2)

                            with col_confirm:
                                if st.button("Yes, delete", key=f"confirm_delete_yes_{key_suffix}", type="primary"):
                                    try:
                                        run_async(delete_recipe_async(recipe_id=recipe.get('id') or recipe.get('name')))
                                        st.success(f"✓ Recipe '{recipe.get('name') or recipe.get('id')}' deleted!")
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
