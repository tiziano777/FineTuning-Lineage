"""Experiment management page."""

from __future__ import annotations

import asyncio
import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.experiment_repository import ExperimentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)


# Async helper functions
async def create_experiment_async(model_id: str, status: str, description: str) -> dict:
    """Create experiment asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.create_experiment(model_id=model_id, status=status, description=description)


async def list_experiments_async(status: str | None = None) -> list[dict]:
    """List experiments asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.list_experiments(status=status)


async def get_experiment_async(exp_id: str) -> dict:
    """Get experiment asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.get_experiment(exp_id)


async def update_experiment_async(
    exp_id: str, status: str, description: str, exit_status: str | None, exit_msg: str | None
) -> dict:
    """Update experiment asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.update_experiment(
        exp_id, status=status, description=description, exit_status=exit_status, exit_msg=exit_msg
    )


async def check_experiment_deps_async(exp_id: str) -> int:
    """Check experiment dependencies asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.count_dependencies(exp_id)


async def delete_experiment_async(exp_id: str) -> None:
    """Delete experiment asynchronously."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    await repo.delete_experiment(exp_id)


def run() -> None:
    """Run experiment management page."""
    st.title("Experiment Management")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])

    with tab_create:
        st.subheader("Create New Experiment")
        with st.form("create_experiment_form"):
            model_id = st.text_input("Model ID", placeholder="UUID")
            status = st.selectbox("Status", ["PENDING", "RUNNING", "COMPLETED", "FAILED"])
            description = st.text_area("Description", value="")
            submitted = st.form_submit_button("Create Experiment")

            if submitted:
                if not model_id.strip():
                    st.error("Model ID is required")
                else:
                    try:
                        result = run_async(
                            create_experiment_async(
                                model_id=model_id,
                                status=status,
                                description=description,
                            )
                        )
                        st.success(f"✓ Experiment '{result['exp_id']}' created successfully!")
                        st.toast("Experiment created!", icon="✅")
                    except UIError as e:
                        st.error(f"Error: {e.user_message}")
                    except asyncio.TimeoutError:
                        st.error("Request timed out. Please try again.")
                        logger.exception("Timeout in create_experiment")
                    except Exception as e:
                        st.error(f"Unexpected error: {str(e)}")
                        logger.exception("Uncaught exception in create_experiment")

    with tab_browse:
        st.subheader("Browse Experiments")
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "PENDING", "RUNNING", "COMPLETED", "FAILED"],
        )

        try:
            filter_val = None if status_filter == "All" else status_filter
            experiments = run_async(list_experiments_async(status=filter_val))

            if experiments:
                for exp in experiments:
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2, 2, 2])
                        with col1:
                            st.write(f"**{exp.get('exp_id', 'N/A')}**")
                        with col2:
                            st.caption(f"Status: {exp.get('status', 'N/A')}")
                        with col3:
                            st.caption(f"Created: {exp.get('created_at', 'N/A')}")
            else:
                st.info("No experiments found.")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_edit:
        st.subheader("Update Experiment")
        try:
            experiments = run_async(list_experiments_async())
            exp_map = {e["exp_id"]: e["id"] for e in experiments}

            selected_exp = st.selectbox("Select Experiment", list(exp_map.keys()))

            if selected_exp:
                exp_id = exp_map[selected_exp]
                exp = run_async(get_experiment_async(exp_id))

                with st.form("edit_experiment_form"):
                    status = st.selectbox(
                        "Status", ["PENDING", "RUNNING", "COMPLETED", "FAILED"], index=["PENDING", "RUNNING", "COMPLETED", "FAILED"].index(exp.get("status", "PENDING"))
                    )
                    description = st.text_area("Description", value=exp.get("description", ""))
                    submitted = st.form_submit_button("Update Experiment")

                    if submitted:
                        try:
                            run_async(
                                update_experiment_async(
                                    exp_id, status=status, description=description, exit_status=None, exit_msg=None
                                )
                            )
                            st.success("✓ Experiment updated!")
                        except UIError as e:
                            st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_delete:
        st.subheader("Delete Experiment")
        try:
            experiments = run_async(list_experiments_async())
            exp_map = {e["exp_id"]: e["id"] for e in experiments}

            selected_exp = st.selectbox("Select Experiment to Delete", list(exp_map.keys()), key="delete")

            if selected_exp:
                exp_id = exp_map[selected_exp]

                try:
                    # Check if experiment can be deleted using repository method
                    db_client = get_neo4j_client()
                    repo = ExperimentRepository(db_client)
                    is_deletable = run_async(repo.is_deletable(exp_id))

                    if not is_deletable:
                        st.warning(
                            "⚠️ This experiment cannot be deleted because:\n"
                            "• It has produced checkpoints, OR\n"
                            "• It has derived/branched experiments, OR\n"
                            "• It has started-from checkpoints, OR\n"
                            "• It has retry experiments\n\n"
                            "Remove dependent experiments/checkpoints first."
                        )
                    else:
                        st.success("✓ No dependencies found. Safe to delete.")
                        confirm = st.checkbox(f"I confirm deletion of experiment '{selected_exp}'")
                        if confirm and st.button("Delete Experiment"):
                            try:
                                run_async(delete_experiment_async(exp_id))
                                st.success("✓ Experiment deleted!")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
                except Exception as e:
                    st.error(f"Error checking dependencies: {str(e)}")
                    logger.exception("Error in delete check")
        except UIError as e:
            st.error(f"Error: {e.user_message}")
