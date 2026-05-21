"""Model management page."""

from __future__ import annotations

import asyncio
import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.model_repository import ModelRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)


# Async helper functions for model operations
async def create_model_async(
    model_name: str, version: str, url: str, doc_url: str, description: str
) -> dict:
    """Create model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.create_model(
        model_name=model_name,
        version=version,
        url=url,
        doc_url=doc_url,
        description=description,
    )


async def list_models_async() -> list[dict]:
    """List models asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.list_models()


async def get_model_async(model_id: str) -> dict:
    """Get model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.get_model(model_id)


async def update_model_async(
    model_id: str, version: str, url: str, doc_url: str, description: str
) -> None:
    """Update model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    await repo.update_model(
        model_id, version=version, url=url, doc_url=doc_url, description=description
    )


async def check_model_deps_async(model_id: str) -> int:
    """Check model dependencies asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.check_model_dependencies(model_id)


async def upsert_model_async(
    model_name: str, version: str, url: str, doc_url: str, description: str
) -> dict:
    """Upsert model by name asynchronously (create if new, update if exists)."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.upsert_by_name(
        model_name=model_name,
        version=version,
        url=url,
        doc_url=doc_url,
        description=description,
    )


async def delete_model_async(model_id: str) -> None:
    """Delete model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    await repo.delete_model(model_id)


def run() -> None:
    """Run model management page."""
    st.title("Model Management")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])

    with tab_create:
        st.subheader("Create New Model")
        with st.form("create_model_form"):
            model_name = st.text_input("Model Name", placeholder="gpt2-large")
            version = st.text_input("Version", value="")
            url = st.text_input("URL", value="")
            doc_url = st.text_input("Documentation URL", value="")
            description = st.text_area("Description", value="")
            upsert_mode = st.checkbox("Upsert mode (update if exists)")
            if upsert_mode:
                st.info("Model will be created if new, or updated if a model with this name already exists.")
            submitted = st.form_submit_button("Save Model")

            if submitted:
                if not model_name.strip():
                    st.error("Model name is required")
                else:
                    try:
                        if upsert_mode:
                            result = run_async(
                                upsert_model_async(
                                    model_name=model_name,
                                    version=version,
                                    url=url,
                                    doc_url=doc_url,
                                    description=description,
                                )
                            )
                            st.success(f"Model '{result['model_name']}' saved successfully!")
                        else:
                            result = run_async(
                                create_model_async(
                                    model_name=model_name,
                                    version=version,
                                    url=url,
                                    doc_url=doc_url,
                                    description=description,
                                )
                            )
                            st.success(f"Model '{result['model_name']}' created successfully!")
                        st.toast("Model saved!", icon="✅")
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except asyncio.TimeoutError:
                        st.error("Request timed out. Please try again.")
                        logger.exception("Timeout in create_model")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in create_model")

    with tab_browse:
        st.subheader("Browse Models")
        try:
            models = run_async(list_models_async())

            if models:
                for model in models:
                    with st.container(border=True):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**{model.get('model_name', 'N/A')}**")
                            st.caption(f"Version: {model.get('version', 'N/A')}")
                        with col2:
                            st.caption(f"Created: {model.get('created_at', 'N/A')}")
            else:
                st.info("No models found.")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_edit:
        st.subheader("Update Model")
        try:
            models = run_async(list_models_async())
            model_names = {m["model_name"]: m["id"] for m in models}

            selected_name = st.selectbox("Select Model", list(model_names.keys()))

            if selected_name:
                model_id = model_names[selected_name]
                model = run_async(get_model_async(model_id))

                if model is None:
                    st.error(f"Model not found: {selected_name} (id={model_id})")
                else:
                    with st.form("edit_model_form"):
                        version = st.text_input("Version", value=model.get("version", ""))
                        url = st.text_input("URL", value=model.get("url", ""))
                        doc_url = st.text_input("Doc URL", value=model.get("doc_url", ""))
                        description = st.text_area("Description", value=model.get("description", ""))
                        submitted = st.form_submit_button("Update Model")

                        if submitted:
                            try:
                                run_async(
                                    update_model_async(
                                        model_id,
                                        version=version,
                                        url=url,
                                        doc_url=doc_url,
                                        description=description,
                                    )
                                )
                                st.success("✓ Model updated!")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_delete:
        st.subheader("Delete Model")
        try:
            models = run_async(list_models_async())
            model_names = {m['model_name']: m['id'] for m in models}

            selected_name = st.selectbox("Select Model to Delete", list(model_names.keys()), key="delete")

            if selected_name:
                model_id = model_names[selected_name]

                try:
                    # Check if model can be deleted using repository method
                    db_client = get_neo4j_client()
                    repo = ModelRepository(db_client)
                    is_deletable = run_async(repo.is_deletable(model_id))

                    if not is_deletable:
                        st.warning(
                            "⚠️ This model cannot be deleted because:\n"
                            "• It has been selected for experiments, OR\n"
                            "• It has been used as base for model merging\n\n"
                            "Remove dependent experiments/models first."
                        )
                    else:
                        st.success("✓ No dependencies found. Safe to delete.")
                        confirm = st.checkbox(f"I confirm deletion of model '{selected_name}'")
                        if confirm and st.button("Delete Model"):
                            try:
                                run_async(delete_model_async(model_id))
                                st.success("✓ Model deleted!")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
                except Exception as e:
                    st.error(f"Error checking dependencies: {str(e)}")
                    logger.exception("Error in delete check")
        except UIError as e:
            st.error(f"Error: {e.user_message}")
