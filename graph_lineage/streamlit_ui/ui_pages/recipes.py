"""Recipe management page."""

from __future__ import annotations

import logging
import streamlit as st
import uuid
from graph_lineage.data_classes.neo4j.nodes.recipe import Recipe, RecipeEntry

from graph_lineage.streamlit_ui.db.repository.recipe_repository import RecipeRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError, DuplicateRecipeError
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.recipe_validation import validate_recipe_yaml
from graph_lineage.streamlit_ui.utils.scope_enum import ScopeEnum
from graph_lineage.streamlit_ui.utils.task_enum import TaskEnum

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Async helpers — ogni operazione di scrittura passa un oggetto Recipe
# ----------------------------------------------------------------------

async def save_recipe_from_yaml_async(yaml_content: str, description: str = "", filename: str | None = None, overwrite: bool = False) -> Recipe:
    """Parsa e persiste una recipe da YAML (create, o upsert se overwrite=True)."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.save_from_yaml(
        yaml_content=yaml_content,
        description=description,
        filename=filename,
        overwrite=overwrite,
    )

async def create_recipe_from_form_async(
    name: str,
    entries_list: list[dict],
    description: str = "",
    scope: str = "",
    tasks: list[str] | None = None,
    tags: list[str] | None = None,
    derived_from: str | None = None,
    recipe_custom_fields: dict | None = None,
) -> Recipe:
    """Costruisce un Recipe dai dati del form e lo crea."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)

    validated_entries = []
    for entry_data in entries_list:
        try:
            validated_entries.append(RecipeEntry(**entry_data))
        except Exception as e:
            raise UIError(f"Invalid entry data: {str(e)}")

    recipe_kwargs = {
        "name": name,
        "entries": validated_entries,
        "description": description,
        "scope": scope,
        "tasks": tasks or [],
        "tags": tags or [],
        "derived_from": derived_from,
    }
    if recipe_custom_fields:
        recipe_kwargs.update(recipe_custom_fields)

    try:
        recipe = Recipe(**recipe_kwargs)
    except Exception as e:
        raise UIError(f"Invalid recipe data: {str(e)}")

    return await repo.create(recipe)

async def update_recipe_async(recipe: Recipe) -> Recipe:
    """Persiste le modifiche su una recipe esistente."""
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.update(recipe)

async def search_recipes_async(query: str) -> list[Recipe]:
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.search(query)

async def list_recipes_async(limit: int = 20) -> list[Recipe]:
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.list_with_limit(limit=limit)

async def delete_recipe_async(recipe_id: str) -> None:
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    await repo.delete(recipe_id=recipe_id)

async def is_recipe_deletable_async(recipe_id: str) -> bool:
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.is_deletable(recipe_id=recipe_id)

async def get_recipe_by_id_async(recipe_id: str) -> Recipe | None:
    db_client = get_neo4j_client()
    repo = RecipeRepository(db_client)
    return await repo.get_by_id(recipe_id)

def run() -> None:
    """Run recipe management page."""
    st.title("Recipe Management")

    tab1, tab2, tab3 = st.tabs(["Upload", "Create", "Browse & Manage"])

    # ------------------------------------------------------------------
    # TAB 1 — Upload YAML
    # ------------------------------------------------------------------
     
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
                    entries_count = len(config.entries) if getattr(config, "entries", None) else 0
                    yaml_name = getattr(config, "name", None)
                    yaml_id = getattr(config, "id", None)
                    yaml_description = getattr(config, "description", None)
                    st.info(
                        f"**Name:** {yaml_name or 'N/A'} | **Recipe ID:** {yaml_id or 'N/A'} | "
                        f"**Description:** {yaml_description or 'N/A'} | **Entries:** {entries_count}"
                    )
                    logger.info("Validation passed for %s: detected_entries=%d", uploaded_file.name, entries_count)

                    existing_recipe = run_async(get_recipe_by_id_async(str(yaml_id))) if yaml_id else None

                    if existing_recipe:
                        st.warning(f"⚠️ A recipe with ID `{yaml_id}` already exists: **{existing_recipe.name}**")
                        if st.button("Confirm Overwrite", key="confirm_overwrite_recipe"):
                            st.session_state["overwrite_recipe_confirmed"] = True

                    can_save = not existing_recipe or st.session_state.get("overwrite_recipe_confirmed", False)

                    if can_save:
                        if st.button("Save Recipe", disabled=st.session_state.get("saving_recipe", False)):
                            st.session_state.saving_recipe = True
                            try:
                                logger.info("Saving recipe from upload: filename=%s", uploaded_file.name)
                                result = run_async(
                                    save_recipe_from_yaml_async(
                                        yaml_content=yaml_content,
                                        description=yaml_description or "",
                                        filename=uploaded_file.name,
                                        overwrite=bool(existing_recipe),
                                    )
                                )
                                entry_count = len(result.entries)
                                action = "overwritten" if existing_recipe else "created"
                                st.success(f"✓ Recipe '{result.name}' {action} successfully! ({entry_count} entries)")
                                st.toast("Recipe saved!", icon="✅")
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

    # ------------------------------------------------------------------
    # TAB 2 — Create from form
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("Create Recipe from Form")

        if "recipe_entries" not in st.session_state:
            st.session_state.recipe_entries = []
        if "recipe_custom_fields" not in st.session_state:
            st.session_state.recipe_custom_fields = {}

        st.markdown("### Recipe Metadata")

        recipe_name = st.text_input(
            "Recipe Name *",
            placeholder="e.g., my-sft-dataset",
            help="Unique name for this recipe",
        )

        recipe_description = st.text_area(
            "Description",
            placeholder="Optional description of what this recipe contains",
            height=100,
        )

        col1, col2 = st.columns(2)
        with col1:
            recipe_scope = st.selectbox(
                "Scope",
                options=[None] + ScopeEnum.values(),
                format_func=lambda x: x if x else "Select scope (optional)",
            )

        with col2:
            recipe_derived_from = st.text_input(
                "Derived From (Recipe ID)",
                placeholder="Optional parent recipe ID",
            )

        valid_tasks = TaskEnum.values()
        selected_tasks = st.multiselect(
            "Tasks",
            options=valid_tasks,
            default=[],
            help="Select relevant tasks",
        )

        tags_input = st.text_area(
            "Tags (one per line)",
            placeholder="tag1\ntag2\ntag3",
            height=80,
        )
        recipe_tags = [tag.strip() for tag in tags_input.split("\n") if tag.strip()]

        st.markdown("### Recipe Custom Fields (Advanced)")
        st.caption("Add additional metadata fields for integration with your data management system")

        col_add_custom, col_remove_custom = st.columns([3, 1])
        with col_add_custom:
            custom_field_key = st.text_input(
                "Custom Field Key",
                key="custom_field_key_input",
                placeholder="e.g., model_version, created_by",
            )
        with col_remove_custom:
            st.write("")
            if st.button("➕ Add Field", key="add_custom_field_btn"):
                if custom_field_key and custom_field_key.strip():
                    key = custom_field_key.strip()
                    if key not in st.session_state.recipe_custom_fields:
                        st.session_state.recipe_custom_fields[key] = ""
                        st.rerun()

        if st.session_state.recipe_custom_fields:
            st.markdown("#### Existing Custom Fields")
            for field_key in list(st.session_state.recipe_custom_fields.keys()):
                col_val, col_del = st.columns([4, 1])
                with col_val:
                    st.session_state.recipe_custom_fields[field_key] = st.text_input(
                        f"Value for '{field_key}'",
                        value=st.session_state.recipe_custom_fields[field_key],
                        key=f"custom_field_val_{field_key}",
                    )
                with col_del:
                    st.write("")
                    if st.button("🗑️ Remove", key=f"remove_custom_{field_key}"):
                        del st.session_state.recipe_custom_fields[field_key]
                        st.rerun()

        st.markdown("### Dataset Entries")
        st.caption("Add one or more dataset entries to this recipe")

        if st.button("➕ Add New Entry", key="add_entry_btn"):
            st.session_state.recipe_entries.append({
                "entry_id": str(uuid.uuid4()),
                "dist_uri": "",
                "dist_id": "",
                "dist_name": "",
                "chat_type": "",
                "replica": 1,
                "samples": None,
                "tokens": None,
                "words": None,
                "system_prompt": {},
                "custom_fields": {},
            })
            st.rerun()

        if st.session_state.recipe_entries:
            st.markdown("#### Entries List")
            for idx, entry in enumerate(st.session_state.recipe_entries):
                with st.expander(f"Entry {idx + 1}: {entry.get('dist_uri', 'New Entry')}", expanded=False):
                    entry["dist_uri"] = st.text_input(
                        "Distribution URI *",
                        value=entry.get("dist_uri", ""),
                        placeholder="e.g., /data/my_dataset or s3://bucket/path",
                        key=f"dist_uri_{entry['entry_id']}",
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        entry["dist_id"] = st.text_input(
                            "Distribution ID",
                            value=entry.get("dist_id", ""),
                            placeholder="Unique distribution ID",
                            key=f"dist_id_{entry['entry_id']}",
                        )
                    with col2:
                        entry["dist_name"] = st.text_input(
                            "Distribution Name",
                            value=entry.get("dist_name", ""),
                            placeholder="Human-readable name",
                            key=f"dist_name_{entry['entry_id']}",
                        )

                    entry["chat_type"] = st.text_input(
                        "Chat Type",
                        value=entry.get("chat_type", ""),
                        placeholder="e.g., conversation, instruction",
                        key=f"chat_type_{entry['entry_id']}",
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        entry["replica"] = st.number_input(
                            "Replica (Oversampling Factor)",
                            value=entry.get("replica", 1),
                            min_value=1,
                            key=f"replica_{entry['entry_id']}",
                        )
                    with col2:
                        entry["samples"] = st.number_input(
                            "Samples",
                            value=entry.get("samples"),
                            min_value=0,
                            key=f"samples_{entry['entry_id']}",
                        )

                    col1, col2 = st.columns(2)
                    with col1:
                        entry["tokens"] = st.number_input(
                            "Tokens",
                            value=entry.get("tokens"),
                            min_value=0,
                            key=f"tokens_{entry['entry_id']}",
                        )
                    with col2:
                        entry["words"] = st.number_input(
                            "Words",
                            value=entry.get("words"),
                            min_value=0,
                            key=f"words_{entry['entry_id']}",
                        )

                    # ─── System Prompts as Dict[str, str] ───
                    st.markdown("##### System Prompts (Dict: name → content)")
                    if "system_prompt" not in entry or not isinstance(entry["system_prompt"], dict):
                        entry["system_prompt"] = {}

                    col_add_prompt, col_remove = st.columns([3, 1])
                    with col_add_prompt:
                        new_prompt_name = st.text_input(
                            "Prompt Name",
                            key=f"new_prompt_name_{entry['entry_id']}",
                            placeholder="e.g., DPO_Text2SQL",
                        )
                    with col_remove:
                        st.write("")
                        if st.button("➕ Add Prompt", key=f"add_prompt_{entry['entry_id']}"):
                            if new_prompt_name and new_prompt_name.strip():
                                pname = new_prompt_name.strip()
                                if pname not in entry["system_prompt"]:
                                    entry["system_prompt"][pname] = ""
                                    st.rerun()

                    # Show existing prompts
                    if entry["system_prompt"]:
                        for prompt_name in list(entry["system_prompt"].keys()):
                            col_val, col_del = st.columns([4, 1])
                            with col_val:
                                entry["system_prompt"][prompt_name] = st.text_area(
                                    f"Content for '{prompt_name}'",
                                    value=entry["system_prompt"][prompt_name],
                                    height=80,
                                    key=f"prompt_content_{entry['entry_id']}_{prompt_name}",
                                )
                            with col_del:
                                st.write("")
                                if st.button("🗑️ Remove", key=f"remove_prompt_{entry['entry_id']}_{prompt_name}"):
                                    del entry["system_prompt"][prompt_name]
                                    st.rerun()

                    st.markdown("#### Entry Custom Fields (Advanced)")
                    col_add, col_remove = st.columns([3, 1])
                    with col_add:
                        custom_key = st.text_input(
                            "Custom Field Key",
                            key=f"entry_custom_key_{entry['entry_id']}",
                            placeholder="e.g., source, version",
                        )
                    with col_remove:
                        st.write("")
                        if st.button("Add", key=f"add_entry_custom_{entry['entry_id']}"):
                            if custom_key and custom_key.strip():
                                k = custom_key.strip()
                                if k not in entry.get("custom_fields", {}):
                                    entry.setdefault("custom_fields", {})[k] = ""
                                    st.rerun()

                    if entry.get("custom_fields"):
                        for field_key in list(entry["custom_fields"].keys()):
                            col_val, col_del = st.columns([4, 1])
                            with col_val:
                                entry["custom_fields"][field_key] = st.text_input(
                                    f"Value for '{field_key}'",
                                    value=entry["custom_fields"][field_key],
                                    key=f"entry_custom_val_{entry['entry_id']}_{field_key}",
                                )
                            with col_del:
                                st.write("")
                                if st.button("Remove", key=f"remove_entry_custom_{entry['entry_id']}_{field_key}"):
                                    del entry["custom_fields"][field_key]
                                    st.rerun()

                    if st.button("🗑️ Delete Entry", key=f"delete_entry_{entry['entry_id']}", type="secondary"):
                        st.session_state.recipe_entries.pop(idx)
                        st.rerun()

        st.markdown("---")
        submit_btn = st.button("✓ Create Recipe", type="primary", key="final_submit_recipe_btn")

        if submit_btn:
            if not recipe_name or not recipe_name.strip():
                st.error("❌ Recipe name is required")
            elif not st.session_state.recipe_entries:
                st.error("❌ At least one entry is required")
            else:
                invalid_entries = [
                    idx for idx, e in enumerate(st.session_state.recipe_entries)
                    if not e.get("dist_uri", "").strip()
                ]
                if invalid_entries:
                    st.error(f"❌ The following entries are missing dist_uri: {invalid_entries}")
                else:
                    final_entries = []
                    for entry in st.session_state.recipe_entries:
                        entry_dict = {
                            "dist_uri": entry["dist_uri"],
                            "dist_id": entry.get("dist_id") or None,
                            "dist_name": entry.get("dist_name") or None,
                            "chat_type": entry.get("chat_type") or None,
                            "replica": entry.get("replica", 1),
                            "samples": entry.get("samples"),
                            "tokens": entry.get("tokens"),
                            "words": entry.get("words"),
                            "system_prompt": entry.get("system_prompt") or None,
                        }
                        if entry.get("custom_fields"):
                            entry_dict.update(entry["custom_fields"])
                        final_entries.append(entry_dict)

                    try:
                        with st.spinner("Creating recipe..."):
                            result = run_async(
                                create_recipe_from_form_async(
                                    name=recipe_name.strip(),
                                    entries_list=final_entries,
                                    description=recipe_description or "",
                                    scope=recipe_scope or "",
                                    tasks=selected_tasks or [],
                                    tags=recipe_tags or [],
                                    derived_from=recipe_derived_from or None,
                                    recipe_custom_fields=st.session_state.recipe_custom_fields or None,
                                )
                            )
                        st.success(f"✓ Recipe '{result.name}' created successfully! ({len(final_entries)} entries)")
                        st.toast("Recipe created!", icon="✅")
                        st.session_state.recipe_entries = []
                        st.session_state.recipe_custom_fields = {}
                        st.rerun()
                    except DuplicateRecipeError as e:
                        st.error(f"❌ Error: {e.user_message}")
                        st.caption(e.details)
                    except UIError as e:
                        st.error(f"❌ Error: {e.user_message}")
                        st.caption(e.details)

    # ------------------------------------------------------------------
    # TAB 3 — Browse & Manage
    # ------------------------------------------------------------------
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

                            custom = recipe.custom_fields
                            if custom:
                                st.write(f"**Custom fields:** {custom}")

                            st.caption(f"Created: {recipe.created_at or 'N/A'}")
                            st.caption(f"Updated: {recipe.updated_at or 'N/A'}")

                            entries = recipe.entries
                            if entries:
                                st.divider()
                                st.subheader("📊 Dataset Entries")

                                for i, entry in enumerate(entries):
                                    st.markdown(f"### 📦 Entry #{i + 1}: `{entry.dist_uri or 'N/A'}`")

                                    full_data = entry.model_dump(exclude_none=True)
                                    full_data.pop("dist_uri", None)
                                    validation_error = full_data.pop("validation_error", None)

                                    sorted_keys = sorted(full_data.keys())
                                    if sorted_keys:
                                        cols = st.columns([1, 1])
                                        mid = (len(sorted_keys) + 1) // 2
                                        left_keys = sorted_keys[:mid]
                                        right_keys = sorted_keys[mid:]

                                        for target_cols, keys in ((cols[0], left_keys), (cols[1], right_keys)):
                                            with target_cols:
                                                for key in keys:
                                                    val = full_data[key]
                                                    if key == "system_prompt" and isinstance(val, dict):
                                                        val_display = ", ".join([f"{k}: {v[:50]}..." if len(v) > 50 else f"{k}: {v}" for k, v in val.items()])
                                                        val = val_display or "(empty)"
                                                    st.write(f"**{key}:** {val}")

                                    if validation_error:
                                        st.error(f"❌ Validation error: {validation_error}")

                                    st.markdown("---")
                            else:
                                st.info("No entries in this recipe")

                        with col2:
                            col_edit, col_delete = st.columns(2)
                            with col_edit:
                                if st.button("✏️ Edit", key=f"edit_{key_suffix}"):
                                    st.session_state[f"edit_recipe_{key_suffix}"] = True

                            with col_delete:
                                can_delete = run_async(is_recipe_deletable_async(recipe.id))
                                if st.button(
                                    "🗑️ Delete",
                                    key=f"delete_{key_suffix}",
                                    disabled=not can_delete,
                                    help="Delete is disabled if recipe is used by experiments",
                                ):
                                    st.session_state[f"confirm_delete_{key_suffix}"] = True

                        # ═══════════════════════════════════════════════════════════════
                        # EDIT RECIPE SECTION — Dinamico per tutti i campi + custom fields
                        # ═══════════════════════════════════════════════════════════════
                        if st.session_state.get(f"edit_recipe_{key_suffix}", False):
                            st.divider()
                            st.subheader("✏️ Edit Recipe")

                            # ── Inizializza session state per edit se non presente ──
                            edit_key = f"edit_state_{key_suffix}"
                            if edit_key not in st.session_state:
                                st.session_state[edit_key] = {
                                    "name": recipe.name or "",
                                    "description": recipe.description or "",
                                    "scope": recipe.scope,
                                    "tasks": list(recipe.tasks or []),
                                    "tags": list(recipe.tags or []),
                                    "derived_from": recipe.derived_from or "",
                                    "custom_fields": dict(recipe.custom_fields or {}),
                                    "entries": [],
                                }
                                # Serializza entries per editing
                                for entry in (recipe.entries or []):
                                    entry_dict = entry.model_dump(exclude_none=True)
                                    entry_custom = entry.custom_fields
                                    st.session_state[edit_key]["entries"].append({
                                        "entry_id": str(uuid.uuid4()),
                                        "dist_uri": entry_dict.get("dist_uri", ""),
                                        "dist_id": entry_dict.get("dist_id", ""),
                                        "dist_name": entry_dict.get("dist_name", ""),
                                        "chat_type": entry_dict.get("chat_type", ""),
                                        "replica": entry_dict.get("replica", 1),
                                        "samples": entry_dict.get("samples"),
                                        "tokens": entry_dict.get("tokens"),
                                        "words": entry_dict.get("words"),
                                        "system_prompt": dict(entry_dict.get("system_prompt") or {}),
                                        "custom_fields": dict(entry_custom or {}),
                                    })

                            edit_state = st.session_state[edit_key]

                            # ═══════ BASE FIELDS ═══════
                            st.markdown("#### Base Fields")
                            edit_state["name"] = st.text_input(
                                "Recipe Name",
                                value=edit_state["name"],
                                key=f"edit_name_{key_suffix}",
                            )
                            edit_state["description"] = st.text_area(
                                "Description",
                                value=edit_state["description"],
                                key=f"edit_desc_{key_suffix}",
                            )

                            current_scope = edit_state.get("scope")
                            selected_scope = st.selectbox(
                                "Scope",
                                options=[None] + ScopeEnum.values(),
                                index=0 if not current_scope else (
                                    ScopeEnum.values().index(current_scope) + 1
                                    if current_scope in ScopeEnum.values() else 0
                                ),
                                key=f"edit_scope_{key_suffix}",
                            )
                            edit_state["scope"] = selected_scope if selected_scope else None

                            valid_enum_values = TaskEnum.values()
                            filtered_tasks = [t for t in edit_state.get("tasks", []) if t in valid_enum_values]
                            edit_state["tasks"] = st.multiselect(
                                "Tasks",
                                options=valid_enum_values,
                                default=filtered_tasks,
                                key=f"edit_tasks_{key_suffix}",
                            )

                            tags_text = st.text_area(
                                "Tags (one per line)",
                                value="\n".join(edit_state.get("tags", [])),
                                key=f"edit_tags_{key_suffix}",
                            )
                            edit_state["tags"] = [tag.strip() for tag in tags_text.split("\n") if tag.strip()]

                            edit_state["derived_from"] = st.text_input(
                                "Derived From (UUID)",
                                value=edit_state.get("derived_from", ""),
                                key=f"edit_derived_{key_suffix}",
                            )

                            # ═══════ CUSTOM FIELDS (RECIPE) ═══════
                            st.markdown("#### Recipe Custom Fields")
                            st.caption("Existing custom fields and ability to add new ones")

                            col_add_recipe_custom, _ = st.columns([3, 1])
                            with col_add_recipe_custom:
                                new_recipe_custom_key = st.text_input(
                                    "New Custom Field Key",
                                    key=f"new_recipe_custom_key_{key_suffix}",
                                    placeholder="e.g., model_version, created_by",
                                )
                            if st.button("➕ Add Recipe Custom Field", key=f"add_recipe_custom_{key_suffix}"):
                                if new_recipe_custom_key and new_recipe_custom_key.strip():
                                    k = new_recipe_custom_key.strip()
                                    if k not in edit_state["custom_fields"]:
                                        edit_state["custom_fields"][k] = ""
                                        st.rerun()

                            if edit_state.get("custom_fields"):
                                for field_key in list(edit_state["custom_fields"].keys()):
                                    col_val, col_del = st.columns([4, 1])
                                    with col_val:
                                        edit_state["custom_fields"][field_key] = st.text_input(
                                            f"Value for '{field_key}'",
                                            value=edit_state["custom_fields"][field_key],
                                            key=f"edit_recipe_custom_val_{key_suffix}_{field_key}",
                                        )
                                    with col_del:
                                        st.write("")
                                        if st.button("🗑️ Remove", key=f"remove_recipe_custom_{key_suffix}_{field_key}"):
                                            del edit_state["custom_fields"][field_key]
                                            st.rerun()

                            # ═══════ ENTRIES EDIT ═══════
                            st.divider()
                            st.markdown("#### 📊 Edit Dataset Entries")

                            if st.button("➕ Add New Entry", key=f"add_edit_entry_{key_suffix}"):
                                edit_state["entries"].append({
                                    "entry_id": str(uuid.uuid4()),
                                    "dist_uri": "",
                                    "dist_id": "",
                                    "dist_name": "",
                                    "chat_type": "",
                                    "replica": 1,
                                    "samples": None,
                                    "tokens": None,
                                    "words": None,
                                    "system_prompt": {},
                                    "custom_fields": {},
                                })
                                st.rerun()

                            # ── Ogni entry è un toggle + container(border=True) ──
                            for idx, entry in enumerate(edit_state["entries"]):
                                entry_id = entry["entry_id"]
                                dist_uri_display = entry.get("dist_uri", "New Entry") or "New Entry"

                                toggle_key = f"toggle_entry_{key_suffix}_{entry_id}"
                                is_open = st.toggle(
                                    f"📦 Entry {idx + 1}: `{dist_uri_display}`",
                                    key=toggle_key,
                                    value=False,
                                )

                                if is_open:
                                    with st.container(border=True):
                                        # ── Base Entry Fields ──
                                        entry["dist_uri"] = st.text_input(
                                            "Distribution URI *",
                                            value=entry.get("dist_uri", ""),
                                            key=f"edit_dist_uri_{key_suffix}_{entry_id}",
                                        )

                                        col1, col2 = st.columns(2)
                                        with col1:
                                            entry["dist_id"] = st.text_input(
                                                "Distribution ID",
                                                value=entry.get("dist_id", ""),
                                                key=f"edit_dist_id_{key_suffix}_{entry_id}",
                                            )
                                        with col2:
                                            entry["dist_name"] = st.text_input(
                                                "Distribution Name",
                                                value=entry.get("dist_name", ""),
                                                key=f"edit_dist_name_{key_suffix}_{entry_id}",
                                            )

                                        entry["chat_type"] = st.text_input(
                                            "Chat Type",
                                            value=entry.get("chat_type", ""),
                                            key=f"edit_chat_type_{key_suffix}_{entry_id}",
                                        )

                                        col1, col2 = st.columns(2)
                                        with col1:
                                            entry["replica"] = st.number_input(
                                                "Replica (Oversampling Factor)",
                                                value=entry.get("replica", 1),
                                                min_value=1,
                                                key=f"edit_replica_{key_suffix}_{entry_id}",
                                            )
                                        with col2:
                                            entry["samples"] = st.number_input(
                                                "Samples",
                                                value=entry.get("samples"),
                                                min_value=0,
                                                key=f"edit_samples_{key_suffix}_{entry_id}",
                                            )

                                        col1, col2 = st.columns(2)
                                        with col1:
                                            entry["tokens"] = st.number_input(
                                                "Tokens",
                                                value=entry.get("tokens"),
                                                min_value=0,
                                                key=f"edit_tokens_{key_suffix}_{entry_id}",
                                            )
                                        with col2:
                                            entry["words"] = st.number_input(
                                                "Words",
                                                value=entry.get("words"),
                                                min_value=0,
                                                key=f"edit_words_{key_suffix}_{entry_id}",
                                            )

                                        # ─── System Prompts as Dict[str, str] ───
                                        st.markdown("##### System Prompts (Dict: name → content)")
                                        if "system_prompt" not in entry or not isinstance(entry["system_prompt"], dict):
                                            entry["system_prompt"] = {}

                                        col_add_prompt, col_remove = st.columns([3, 1])
                                        with col_add_prompt:
                                            new_prompt_name = st.text_input(
                                                "Prompt Name",
                                                key=f"edit_new_prompt_name_{key_suffix}_{entry_id}",
                                                placeholder="e.g., DPO_Text2SQL",
                                            )
                                        with col_remove:
                                            st.write("")
                                            if st.button("➕ Add Prompt", key=f"edit_add_prompt_{key_suffix}_{entry_id}"):
                                                if new_prompt_name and new_prompt_name.strip():
                                                    pname = new_prompt_name.strip()
                                                    if pname not in entry["system_prompt"]:
                                                        entry["system_prompt"][pname] = ""
                                                        st.rerun()

                                        # Show existing prompts
                                        if entry["system_prompt"]:
                                            for prompt_name in list(entry["system_prompt"].keys()):
                                                col_val, col_del = st.columns([4, 1])
                                                with col_val:
                                                    entry["system_prompt"][prompt_name] = st.text_area(
                                                        f"Content for '{prompt_name}'",
                                                        value=entry["system_prompt"][prompt_name],
                                                        height=80,
                                                        key=f"edit_prompt_content_{key_suffix}_{entry_id}_{prompt_name}",
                                                    )
                                                with col_del:
                                                    st.write("")
                                                    if st.button("🗑️ Remove", key=f"edit_remove_prompt_{key_suffix}_{entry_id}_{prompt_name}"):
                                                        del entry["system_prompt"][prompt_name]
                                                        st.rerun()

                                        # ── Entry Custom Fields ──
                                        st.markdown("##### Entry Custom Fields")
                                        col_add, _ = st.columns([3, 1])
                                        with col_add:
                                            new_entry_custom_key = st.text_input(
                                                "New Custom Field Key",
                                                key=f"new_entry_custom_key_{key_suffix}_{entry_id}",
                                                placeholder="e.g., source, version",
                                            )
                                        if st.button("➕ Add Entry Custom Field", key=f"add_entry_custom_{key_suffix}_{entry_id}"):
                                            if new_entry_custom_key and new_entry_custom_key.strip():
                                                k = new_entry_custom_key.strip()
                                                if k not in entry.get("custom_fields", {}):
                                                    entry.setdefault("custom_fields", {})[k] = ""
                                                    st.rerun()

                                        if entry.get("custom_fields"):
                                            for field_key in list(entry["custom_fields"].keys()):
                                                col_val, col_del = st.columns([4, 1])
                                                with col_val:
                                                    entry["custom_fields"][field_key] = st.text_input(
                                                        f"Value for '{field_key}'",
                                                        value=entry["custom_fields"][field_key],
                                                        key=f"edit_entry_custom_val_{key_suffix}_{entry_id}_{field_key}",
                                                    )
                                                with col_del:
                                                    st.write("")
                                                    if st.button("🗑️ Remove", key=f"remove_entry_custom_{key_suffix}_{entry_id}_{field_key}"):
                                                        del entry["custom_fields"][field_key]
                                                        st.rerun()

                                        if st.button("🗑️ Delete Entry", key=f"delete_edit_entry_{key_suffix}_{entry_id}", type="secondary"):
                                            edit_state["entries"].pop(idx)
                                            st.rerun()

                                st.markdown("<hr style='margin: 0.5rem 0; border-color: #333;'>", unsafe_allow_html=True)

                            # ═══════ SAVE / CANCEL ═══════
                            st.divider()
                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                if st.button("💾 Save All Changes", key=f"save_edit_{key_suffix}", type="primary"):
                                    try:
                                        # Ricostruisci gli oggetti RecipeEntry
                                        updated_entries = []
                                        for e in edit_state["entries"]:
                                            entry_data = {
                                                "dist_uri": e["dist_uri"],
                                                "dist_id": e["dist_id"] or None,
                                                "dist_name": e["dist_name"] or None,
                                                "chat_type": e["chat_type"] or None,
                                                "replica": e["replica"],
                                                "samples": e["samples"],
                                                "tokens": e["tokens"],
                                                "words": e["words"],
                                                "system_prompt": e["system_prompt"] if e["system_prompt"] else None,
                                            }
                                            # Aggiungi custom fields
                                            for ck, cv in e.get("custom_fields", {}).items():
                                                entry_data[ck] = cv
                                            updated_entries.append(RecipeEntry(**entry_data))

                                        # Ricostruisci l'oggetto Recipe
                                        update_data = {
                                            "name": edit_state["name"].strip() if edit_state["name"].strip() else recipe.name,
                                            "description": edit_state["description"] or None,
                                            "scope": edit_state["scope"],
                                            "tasks": edit_state["tasks"] if edit_state["tasks"] else None,
                                            "tags": edit_state["tags"] if edit_state["tags"] else None,
                                            "derived_from": edit_state["derived_from"] or None,
                                            "entries": updated_entries,
                                        }
                                        # Aggiungi custom fields della recipe
                                        for ck, cv in edit_state.get("custom_fields", {}).items():
                                            update_data[ck] = cv

                                        updated_recipe = recipe.model_copy(update=update_data)
                                        run_async(update_recipe_async(updated_recipe))
                                        st.success("✓ Recipe updated successfully!")
                                        st.session_state[f"edit_recipe_{key_suffix}"] = False
                                        del st.session_state[edit_key]
                                        st.rerun()
                                    except UIError as e:
                                        msg = str(e)
                                        if "already exists" in msg:
                                            st.error(f"Name conflict: {msg}")
                                            st.info("Choose a different name and try again.")
                                        else:
                                            st.error(f"Error: {e}")
                                    except Exception as e:
                                        st.error(f"Validation error: {e}")

                            with col_cancel:
                                if st.button("❌ Cancel", key=f"cancel_edit_{key_suffix}"):
                                    st.session_state[f"edit_recipe_{key_suffix}"] = False
                                    if edit_key in st.session_state:
                                        del st.session_state[edit_key]
                                    st.rerun()

                        # ═══════════════════════════════════════════════════════════════
                        # DELETE CONFIRMATION (invariato)
                        # ═══════════════════════════════════════════════════════════════
                        if st.session_state.get(f"confirm_delete_{key_suffix}", False):
                            st.divider()
                            st.warning(f"⚠️ Are you sure you want to delete '{recipe.name or recipe.id}'?")
                            col_confirm, col_cancel = st.columns(2)

                            with col_confirm:
                                if st.button("Yes, delete", key=f"confirm_delete_yes_{key_suffix}", type="primary"):
                                    try:
                                        run_async(delete_recipe_async(recipe_id=recipe.id))
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

            