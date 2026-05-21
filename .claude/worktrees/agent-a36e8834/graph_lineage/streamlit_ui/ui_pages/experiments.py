"""Experiment management page (read-only browse + metadata edit + soft-delete)."""

from __future__ import annotations

import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.experiment_repository import ExperimentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.history.repository import ExperimentRepository as HistoryRepository

logger = logging.getLogger(__name__)


# Async helper functions
async def list_rich_async(status_filter: str | None = None, search: str | None = None) -> list[dict]:
    """List experiments with rich relationship data."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.list_rich(status_filter=status_filter, search=search)


async def update_metadata_async(exp_id: str, description: str | None = None, notes: str | None = None) -> dict:
    """Update experiment metadata (description/notes only)."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.update_metadata(exp_id=exp_id, description=description, notes=notes)


async def set_visibility_async(exp_id: str, usable: bool) -> list[str]:
    """Toggle experiment visibility via history repository."""
    db_client = get_neo4j_client()
    history_repo = HistoryRepository(db_client)
    return await history_repo.set_visibility(exp_id, usable)


def _status_badge(status: str | None, usable: bool | None) -> str:
    """Return colored status badge markdown."""
    if usable is False:
        return ":gray[HIDDEN]"
    if status == "COMPLETED":
        return ":green[COMPLETED]"
    if status == "RUNNING":
        return ":orange[RUNNING]"
    if status == "FAILED":
        return ":red[FAILED]"
    return f":blue[{status or 'UNKNOWN'}]"


def run() -> None:
    """Run experiment management page."""
    st.title("Experiment Management")

    tab_browse, tab_edit, tab_visibility = st.tabs(["Browse", "Edit Metadata", "Visibility"])

    with tab_browse:
        st.subheader("Browse Experiments")

        col_filter, col_search = st.columns([1, 2])
        with col_filter:
            status_filter = st.selectbox(
                "Status",
                ["All", "COMPLETED", "RUNNING", "FAILED"],
            )
        with col_search:
            search = st.text_input("Search", placeholder="Filter by exp_id or description")

        try:
            filter_val = None if status_filter == "All" else status_filter
            search_val = search.strip() if search and search.strip() else None
            experiments = run_async(list_rich_async(status_filter=filter_val, search=search_val))

            if experiments:
                for exp in experiments:
                    badge = _status_badge(exp.get("status"), exp.get("usable"))
                    label = f"{exp.get('exp_id', 'N/A')} {badge}"
                    with st.expander(label):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Model:** {exp.get('model_name', 'N/A')}")
                            st.markdown(f"**Recipe:** {exp.get('recipe_name', 'N/A')}")
                            if exp.get("technique_code"):
                                st.markdown(
                                    f"**Technique:** {exp.get('technique_code')} "
                                    f"({exp.get('framework_code', 'N/A')})"
                                )
                        with col2:
                            st.markdown(f"**Checkpoints:** {exp.get('ckp_count', 0)}")
                            st.caption(f"Config hash: {exp.get('config_hash', 'N/A')}")
                            st.caption(f"Created: {exp.get('created_at', 'N/A')}")
                        if exp.get("description"):
                            st.markdown(f"**Description:** {exp.get('description')}")
                        if exp.get("notes"):
                            st.markdown(f"**Notes:** {exp.get('notes')}")
            else:
                st.info(
                    "No experiments found",
                    icon=":material/science:",
                )
                st.caption(
                    "Experiments are created automatically when you run a "
                    "training function with @envelope.tracker()."
                )
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_edit:
        st.subheader("Edit Metadata")
        try:
            experiments = run_async(list_rich_async())

            if not experiments:
                st.info("No experiments available to edit.")
                return

            exp_ids = [e["exp_id"] for e in experiments]
            selected_exp_id = st.selectbox("Select Experiment", exp_ids, key="edit_exp")

            if selected_exp_id:
                current = next((e for e in experiments if e["exp_id"] == selected_exp_id), None)
                if current:
                    with st.form("edit_metadata_form"):
                        description = st.text_area(
                            "Description",
                            value=current.get("description", "") or "",
                        )
                        notes = st.text_area(
                            "Notes",
                            value=current.get("notes", "") or "",
                        )
                        submitted = st.form_submit_button("Save Metadata")

                        if submitted:
                            try:
                                run_async(
                                    update_metadata_async(
                                        exp_id=selected_exp_id,
                                        description=description,
                                        notes=notes,
                                    )
                                )
                                st.success("Metadata updated successfully!")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_visibility:
        st.subheader("Experiment Visibility")
        try:
            experiments = run_async(list_rich_async())

            if not experiments:
                st.info("No experiments available.")
                return

            exp_ids = [e["exp_id"] for e in experiments]
            selected_exp_id = st.selectbox("Select Experiment", exp_ids, key="vis_exp")

            if selected_exp_id:
                current = next((e for e in experiments if e["exp_id"] == selected_exp_id), None)
                if current:
                    is_usable = current.get("usable", True)
                    if is_usable is not False:
                        st.markdown("**Current status:** Visible")
                        st.warning("This will hide the experiment from browse views.")
                        confirm = st.checkbox(
                            "I understand this experiment will be hidden",
                            key="confirm_hide_exp",
                        )
                        if confirm and st.button("Hide Experiment"):
                            try:
                                affected = run_async(set_visibility_async(selected_exp_id, False))
                                st.success(f"Experiment hidden. Affected: {len(affected)} experiment(s).")
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
                    else:
                        st.markdown("**Current status:** :gray[HIDDEN]")
                        if st.button("Restore Experiment"):
                            try:
                                affected = run_async(set_visibility_async(selected_exp_id, True))
                                st.success(
                                    f"Experiment restored. Affected: {len(affected)} experiment(s) "
                                    "(including ancestor chain)."
                                )
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")
