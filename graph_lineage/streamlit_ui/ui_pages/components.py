"""Component management page."""

from __future__ import annotations

import asyncio
import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.component_repository import ComponentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)

_SETUPS_PREFIX = "./graph_lineage/setups/"

# Async helper functions
async def create_component_async(
    name: str,
    opt_code: str,
    technique_code: str,
    framework_code: str,
    uri: str,
    docs_url: str,
    description: str,
) -> dict:
    """Create component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    return await repo.create_component(
        name=name,
        opt_code=opt_code,
        technique_code=technique_code,
        framework_code=framework_code,
        uri=uri,
        docs_url=docs_url,
        description=description,
    )

async def list_components_async() -> list[dict]:
    """List components asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    return await repo.list_components()

async def get_component_async(comp_id: str) -> dict:
    """Get component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    return await repo.get_component(comp_id)

async def update_component_async(
    comp_id: str,
    name: str,
    uri: str,
    docs_url: str,
    description: str,
) -> None:
    """Update component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    await repo.update_component(comp_id, name=name, uri=uri, docs_url=docs_url, description=description)

async def check_component_deps_async(comp_id: str) -> int:
    """Check component dependencies asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    return await repo.check_component_dependencies(comp_id)

async def delete_component_async(comp_id: str) -> None:
    """Delete component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    await repo.delete_component(comp_id)

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
                st.rerun()

    # Step 2: Fill remaining fields with pre-filled URI
    elif st.session_state.wizard_step == 2:
        st.markdown("**Step 2: Component Details**")

        # Pre-fill URI from name
        default_uri = f"{_SETUPS_PREFIX}{st.session_state.wizard_name}"

        with st.form("create_component_form"):
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

            col_submit_back, col_submit_create = st.columns(2)
            with col_submit_back:
                back = st.form_submit_button("← Back", use_container_width=True)
            with col_submit_create:
                submitted = st.form_submit_button("Create Component", type="primary", use_container_width=True)

            if back:
                st.session_state.wizard_step = 1
                st.session_state.wizard_name = ""
                st.rerun()

            if submitted:
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
                            )
                        )
                        st.success(f"✓ Component '{result['name']}' created (uri: {result['uri']})")
                        st.toast("Component created!", icon="✅")
                        # Reset wizard
                        st.session_state.wizard_step = 1
                        st.session_state.wizard_name = ""
                        st.rerun()
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except asyncio.TimeoutError:
                        st.error("Request timed out. Please try again.")
                        logger.exception("Timeout in create_component")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in create_component")


def run() -> None:
    """Run component management page."""
    st.title("Component Management")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])

    with tab_create:
        _render_create_wizard()

    with tab_browse:
        st.subheader("Browse Components")
        try:
            components = run_async(list_components_async())

            if components:
                for comp in components:
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2, 2, 2])
                        with col1:
                            st.write(f"**{comp.get('name', 'N/A')}**")
                            st.caption(f"uri: `{comp.get('uri', '')}`")
                        with col2:
                            st.caption(f"Technique: {comp.get('technique_code', 'N/A')}")
                            st.caption(f"Framework: {comp.get('framework_code', 'N/A')}")
                        with col3:
                            st.caption(f"Opt: {comp.get('opt_code', 'N/A')}")
                            if comp.get('docs_url'):
                                st.caption(f"Docs: {comp['docs_url']}")
            else:
                st.info("No components found. Create a component using the Create tab, or they will be auto-created by the tracker hook.")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_edit:
        st.subheader("Update Component")
        try:
            components = run_async(list_components_async())
            comp_map = {f"{c.get('name', c['id'])} ({c['technique_code']})": c["id"] for c in components}

            selected_comp = st.selectbox("Select Component", list(comp_map.keys()))

            if selected_comp:
                comp_id = comp_map[selected_comp]
                comp = run_async(get_component_async(comp_id))

                with st.form("edit_component_form"):
                    name_edit = st.text_input(
                        "Component Name",
                        value=comp.get("name", ""),
                        help="Changing name will update the setup URI automatically unless you override it below.",
                    )
                    uri_edit = st.text_input(
                        "Setup URI",
                        value=comp.get("uri", ""),
                        help="Leave blank to auto-derive from name.",
                    )
                    docs_url_edit = st.text_input("Docs URL", value=comp.get("docs_url", ""))
                    description_edit = st.text_area("Description", value=comp.get("description", ""))
                    submitted = st.form_submit_button("Update Component")

                    if submitted:
                        try:
                            run_async(
                                update_component_async(
                                    comp_id,
                                    name=name_edit.strip(),
                                    uri=uri_edit.strip(),
                                    docs_url=docs_url_edit,
                                    description=description_edit,
                                )
                            )
                            st.success("✓ Component updated!")
                        except UIError as e:
                            st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_delete:
        st.subheader("Delete Component")
        try:
            components = run_async(list_components_async())
            comp_map = {f"{c.get('name', c['id'])} ({c['technique_code']})": c["id"] for c in components}

            selected_comp = st.selectbox("Select Component to Delete", list(comp_map.keys()), key="delete")

            if selected_comp:
                comp_id = comp_map[selected_comp]

                try:
                    db_client = get_neo4j_client()
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
