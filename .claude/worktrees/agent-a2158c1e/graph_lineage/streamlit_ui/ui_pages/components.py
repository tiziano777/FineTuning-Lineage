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


# Async helper functions
async def create_component_async(
    opt_code: str, technique_code: str, framework_code: str, docs_url: str, description: str
) -> dict:
    """Create component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    return await repo.create_component(
        opt_code=opt_code,
        technique_code=technique_code,
        framework_code=framework_code,
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


async def update_component_async(comp_id: str, docs_url: str, description: str) -> None:
    """Update component asynchronously."""
    db_client = get_neo4j_client()
    repo = ComponentRepository(db_client)
    await repo.update_component(comp_id, docs_url=docs_url, description=description)


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


def run() -> None:
    """Run component management page."""
    st.title("Component Management")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])

    with tab_create:
        st.subheader("Create New Component")
        with st.form("create_component_form"):
            opt_code = st.text_input("Optimization Code", placeholder="lora")
            technique_code = st.text_input("Technique Code", placeholder="lora_grpo")
            framework_code = st.text_input("Framework Code", placeholder="unsloth")
            docs_url = st.text_input("Documentation URL", value="")
            description = st.text_area("Description", value="")
            submitted = st.form_submit_button("Create Component")

            if submitted:
                if not all([opt_code.strip(), technique_code.strip(), framework_code.strip()]):
                    st.error("All code fields are required")
                else:
                    try:
                        result = run_async(
                            create_component_async(
                                opt_code=opt_code,
                                technique_code=technique_code,
                                framework_code=framework_code,
                                docs_url=docs_url,
                                description=description,
                            )
                        )
                        st.success(f"✓ Component '{result['opt_code']}' created successfully!")
                        st.toast("Component created!", icon="✅")
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except asyncio.TimeoutError:
                        st.error("Request timed out. Please try again.")
                        logger.exception("Timeout in create_component")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in create_component")

    with tab_browse:
        st.subheader("Browse Components")
        try:
            components = run_async(list_components_async())

            if components:
                for comp in components:
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2, 2, 2])
                        with col1:
                            st.write(f"**{comp.get('opt_code', 'N/A')}**")
                        with col2:
                            st.caption(f"Technique: {comp.get('technique_code', 'N/A')}")
                        with col3:
                            st.caption(f"Framework: {comp.get('framework_code', 'N/A')}")
            else:
                st.info("No components found.")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_edit:
        st.subheader("Update Component")
        try:
            components = run_async(list_components_async())
            comp_map = {f"{c['opt_code']} ({c['technique_code']})" : c["id"] for c in components}

            selected_comp = st.selectbox("Select Component", list(comp_map.keys()))

            if selected_comp:
                comp_id = comp_map[selected_comp]
                comp = run_async(get_component_async(comp_id))

                with st.form("edit_component_form"):
                    docs_url = st.text_input("Doc URL", value=comp.get("docs_url", ""))
                    description = st.text_area("Description", value=comp.get("description", ""))
                    submitted = st.form_submit_button("Update Component")

                    if submitted:
                        try:
                            run_async(
                                update_component_async(comp_id, docs_url=docs_url, description=description)
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
            comp_map = {f"{c['opt_code']} ({c['technique_code']})" : c["id"] for c in components}

            selected_comp = st.selectbox("Select Component to Delete", list(comp_map.keys()), key="delete")

            if selected_comp:
                comp_id = comp_map[selected_comp]

                try:
                    # Check if component can be deleted using repository method
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
