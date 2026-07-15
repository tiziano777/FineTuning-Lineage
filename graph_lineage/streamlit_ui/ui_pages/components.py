"""Component management page."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.component_repository import ComponentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.data_classes.neo4j.nodes.component import Component

logger = logging.getLogger(__name__)

_SETUPS_PREFIX = "./graph_lineage/setups/"

# ────────────────────────────────────────────────────────────────────────────
# DB Layer (async helpers) — Separated from UI logic
# ────────────────────────────────────────────────────────────────────────────

async def create_component_async(
    name: str,
    opt_code: str,
    technique_code: str,
    framework_code: str,
    uri: str,
    docs_url: str,
    description: str,
    **extra_fields: Any,
) -> Component:
    """Create component asynchronously. Returns Component dataclass."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    return await repo.create_from_params(
        name=name,
        opt_code=opt_code,
        technique_code=technique_code,
        framework_code=framework_code,
        uri=uri,
        docs_url=docs_url,
        description=description,
        **extra_fields,
    )

async def list_components_async() -> list[Component]:
    """List components asynchronously. Returns list of Component dataclasses."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    return await repo.list_components()

async def get_component_async(comp_id: str) -> Component | None:
    """Get component asynchronously. Returns Component dataclass or None."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    return await repo.get_component(comp_id)

async def update_component_async(
    comp_id: str,
    name: str,
    uri: str,
    docs_url: str,
    description: str,
    **extra_fields: Any,
) -> Component:
    """Update component asynchronously. Returns updated Component dataclass."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    return await repo.update_component(
        comp_id, name=name, uri=uri, docs_url=docs_url, description=description,
        **extra_fields,
    )

async def check_component_deps_async(comp_id: str) -> int:
    """Check component dependencies asynchronously."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    return await repo.check_component_dependencies(comp_id)

async def delete_component_async(comp_id: str) -> None:
    """Delete component asynchronously."""
    db_client = st.session_state.get("db_client")
    repo = ComponentRepository(db_client)
    await repo.delete_component(comp_id)


# ────────────────────────────────────────────────────────────────────────────
# Extra Fields UI Helpers
# ────────────────────────────────────────────────────────────────────────────

def _init_extra_fields_state(prefix: str) -> None:
    """Initialize session state for extra fields management."""
    key_list = f"{prefix}_extra_fields"
    key_counter = f"{prefix}_extra_counter"
    if key_list not in st.session_state:
        st.session_state[key_list] = []
    if key_counter not in st.session_state:
        st.session_state[key_counter] = 0


def _render_extra_fields_ui(prefix: str, existing_extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render UI for adding/removing custom extra fields.

    Returns a dict of key-value pairs for extra fields.
    Uses session state to track dynamic fields (no forms!).
    """
    _init_extra_fields_state(prefix)

    key_list = f"{prefix}_extra_fields"
    key_counter = f"{prefix}_extra_counter"

    # Pre-populate from existing extras if provided (edit mode)
    if existing_extras and not st.session_state[key_list]:
        for k, v in existing_extras.items():
            st.session_state[key_counter] += 1
            field_id = st.session_state[key_counter]
            st.session_state[key_list].append({
                "id": field_id,
                "key": k,
                "value": str(v),
            })

    st.markdown("---")
    st.markdown("**Custom Metadata Fields** *(optional)*")
    st.caption("Add any extra key-value metadata you want to store with this component.")

    extras = {}

    # Render existing extra fields
    to_remove = []
    for idx, field in enumerate(st.session_state[key_list]):
        col1, col2, col3 = st.columns([3, 4, 1])
        with col1:
            field_key = st.text_input(
                "Key",
                value=field["key"],
                key=f"{prefix}_extra_key_{field['id']}",
                label_visibility="collapsed",
                placeholder="e.g. author",
            )
        with col2:
            field_value = st.text_input(
                "Value",
                value=field["value"],
                key=f"{prefix}_extra_value_{field['id']}",
                label_visibility="collapsed",
                placeholder="e.g. team-alpha",
            )
        with col3:
            if st.button("🗑️", key=f"{prefix}_extra_del_{field['id']}", help="Remove this field"):
                to_remove.append(idx)

        if field_key.strip():
            extras[field_key.strip()] = field_value

    # Remove marked fields
    if to_remove:
        for idx in sorted(to_remove, reverse=True):
            st.session_state[key_list].pop(idx)
        st.rerun()

    # Add new field button
    if st.button("➕ Add Custom Field", key=f"{prefix}_add_extra"):
        st.session_state[key_counter] += 1
        st.session_state[key_list].append({
            "id": st.session_state[key_counter],
            "key": "",
            "value": "",
        })
        st.rerun()

    return extras


def _clear_extra_fields_state(prefix: str) -> None:
    """Clear extra fields from session state."""
    key_list = f"{prefix}_extra_fields"
    key_counter = f"{prefix}_extra_counter"
    if key_list in st.session_state:
        del st.session_state[key_list]
    if key_counter in st.session_state:
        del st.session_state[key_counter]


# ────────────────────────────────────────────────────────────────────────────
# Create Wizard
# ────────────────────────────────────────────────────────────────────────────

def _render_create_wizard() -> None:
    """Render the create component wizard with two steps."""
    # Initialize wizard state
    if "wizard_step" not in st.session_state:
        st.session_state.wizard_step = 1
    if "wizard_name" not in st.session_state:
        st.session_state.wizard_name = ""

    st.subheader("Create New Component")

    # Step 1: Input component name
    if st.session_state.wizard_step == 1:
        st.markdown("**Step 1: Component Name**")
        name_input = st.text_input(
            "Component Name *",
            placeholder="dpo_trl",
            help="Must match the setup template folder name under graph_lineage/setups/",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Next →", type="primary", disabled=not name_input.strip()):
                st.session_state.wizard_step = 2
                st.session_state.wizard_name = name_input.strip()
                st.rerun()
        with col2:
            if st.button("Cancel"):
                st.session_state.wizard_step = 1
                st.session_state.wizard_name = ""
                _clear_extra_fields_state("create")
                st.rerun()

    # Step 2: Fill remaining fields with pre-filled URI + extra fields
    elif st.session_state.wizard_step == 2:
        st.markdown("**Step 2: Component Details**")

        # Pre-fill URI from name
        default_uri = f"{_SETUPS_PREFIX}{st.session_state.wizard_name}"

        col1, col2 = st.columns(2)

        with col1:
            st.text_input(
                "Component Name",
                value=st.session_state.wizard_name,
                disabled=True,
                help="Component name from Step 1",
            )

            uri = st.text_input(
                "Setup URI",
                value=default_uri,
                placeholder=f"{_SETUPS_PREFIX}dpo_trl",
                help="Internal path to the setup template. Can be modified if needed.",
            )

            opt_code = st.text_input("Optimization Code", placeholder="lora")

        with col2:
            technique_code = st.text_input("Technique Code *", placeholder="lora_grpo")
            framework_code = st.text_input("Framework Code *", placeholder="unsloth")
            docs_url = st.text_input("Docs URL", placeholder="https://...")

        description = st.text_area("Description", value="")

        # Extra custom fields (dynamic, outside form!)
        extra_fields = _render_extra_fields_ui("create")

        # Action buttons
        col_back, col_create = st.columns(2)
        with col_back:
            if st.button("← Back", use_container_width=True):
                st.session_state.wizard_step = 1
                st.session_state.wizard_name = ""
                _clear_extra_fields_state("create")
                st.rerun()
        with col_create:
            if st.button("Create Component", type="primary", use_container_width=True):
                if not all([technique_code.strip(), framework_code.strip()]):
                    st.error("Technique Code and Framework Code are required")
                else:
                    try:
                        result = run_async(
                            create_component_async(
                                name=st.session_state.wizard_name,
                                opt_code=opt_code.strip() if opt_code.strip() else "",
                                technique_code=technique_code.strip(),
                                framework_code=framework_code.strip(),
                                uri=uri.strip(),
                                docs_url=docs_url.strip(),
                                description=description.strip(),
                                **extra_fields,
                            )
                        )
                        st.success(f"✓ Component '{result.name}' created (uri: {result.uri})")
                        st.toast("Component created!", icon="✅")
                        # Reset wizard
                        st.session_state.wizard_step = 1
                        st.session_state.wizard_name = ""
                        _clear_extra_fields_state("create")
                        st.rerun()
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except asyncio.TimeoutError:
                        st.error("Request timed out. Please try again.")
                        logger.exception("Timeout in create_component")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in create_component")


# ────────────────────────────────────────────────────────────────────────────
# Browse
# ────────────────────────────────────────────────────────────────────────────

def _render_browse() -> None:
    """Render the browse components tab."""
    st.subheader("Browse Components")
    try:
        components = run_async(list_components_async())

        if components:
            for comp in components:
                with st.container(border=True):
                    col1, col2, col3 = st.columns([2, 2, 2])
                    with col1:
                        st.write(f"**{comp.name}**")
                        st.caption(f"uri: `{comp.uri}`")
                    with col2:
                        st.caption(f"Technique: {comp.technique_code}")
                        st.caption(f"Framework: {comp.framework_code}")
                    with col3:
                        st.caption(f"Opt: {comp.opt_code}")
                        if comp.docs_url:
                            st.caption(f"Docs: {comp.docs_url}")

                    # Show custom fields if any
                    custom = comp.custom_fields
                    if custom:
                        with st.expander(f"📎 {len(custom)} custom field(s)"):
                            for k, v in custom.items():
                                st.write(f"- **{k}**: `{v}`")
        else:
            st.info("No components found. Create a component using the Create tab, or they will be auto-created by the tracker hook.")
    except UIError as e:
        st.error(f"Error: {e.user_message}")


# ────────────────────────────────────────────────────────────────────────────
# Edit
# ────────────────────────────────────────────────────────────────────────────

def _render_edit() -> None:
    """Render the edit component tab."""
    st.subheader("Update Component")
    try:
        components = run_async(list_components_async())
        comp_map = {f"{c.name} ({c.technique_code})": c.id for c in components}

        selected_comp = st.selectbox("Select Component", list(comp_map.keys()), key="edit_select")

        if selected_comp:
            comp_id = comp_map[selected_comp]
            comp = run_async(get_component_async(comp_id))

            name_edit = st.text_input(
                "Component Name",
                value=comp.name or "",
                help="Changing name will update the setup URI automatically unless you override it below.",
            )
            uri_edit = st.text_input(
                "Setup URI",
                value=comp.uri or "",
                help="Leave blank to auto-derive from name.",
            )
            docs_url_edit = st.text_input("Docs URL", value=comp.docs_url or "")
            description_edit = st.text_area("Description", value=comp.description or "")

            # Extra fields UI with existing values pre-populated
            extra_fields = _render_extra_fields_ui("edit", existing_extras=comp.custom_fields or None)

            if st.button("Update Component", type="primary"):
                try:
                    run_async(
                        update_component_async(
                            comp_id,
                            name=name_edit.strip(),
                            uri=uri_edit.strip(),
                            docs_url=docs_url_edit,
                            description=description_edit,
                            **extra_fields,
                        )
                    )
                    st.success("✓ Component updated!")
                    _clear_extra_fields_state("edit")
                    st.rerun()
                except UIError as e:
                    st.error(f"Error: {e.user_message}")
    except UIError as e:
        st.error(f"Error: {e.user_message}")


# ────────────────────────────────────────────────────────────────────────────
# Delete
# ────────────────────────────────────────────────────────────────────────────

def _render_delete() -> None:
    """Render the delete component tab."""
    st.subheader("Delete Component")
    try:
        components = run_async(list_components_async())
        comp_map = {f"{c.name} ({c.technique_code})": c.id for c in components}

        selected_comp = st.selectbox("Select Component to Delete", list(comp_map.keys()), key="delete_select")

        if selected_comp:
            comp_id = comp_map[selected_comp]

            try:
                db_client = st.session_state.get("db_client")
                repo = ComponentRepository(db_client)
                is_deletable = run_async(repo.is_deletable(comp_id))

                if not is_deletable:
                    st.warning(
                        "⚠️ This component cannot be deleted because:\n"
                        "• It has been used by one or more experiments\n\n"
                        "Remove experiments using this component first."
                    )
                else:
                    st.success("✓ No dependencies found. Safe to delete.")
                    confirm = st.checkbox(f"I confirm deletion of component '{selected_comp}'")
                    if confirm and st.button("Delete Component"):
                        try:
                            run_async(delete_component_async(comp_id))
                            st.success("✓ Component deleted!")
                        except UIError as e:
                            st.error(f"Error: {e.user_message}")
            except Exception as e:
                st.error(f"Error checking dependencies: {str(e)}")
                logger.exception("Error in delete check")
    except UIError as e:
        st.error(f"Error: {e.user_message}")


# ────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ────────────────────────────────────────────────────────────────────────────

def run() -> None:
    """Run component management page."""
    st.title("Component Management")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])

    with tab_create:
        _render_create_wizard()

    with tab_browse:
        _render_browse()

    with tab_edit:
        _render_edit()

    with tab_delete:
        _render_delete()