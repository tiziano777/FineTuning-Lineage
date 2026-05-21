"""Checkpoint management page (browse + URI edit wizard + soft-delete)."""

from __future__ import annotations

import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.checkpoint_repository import CheckpointRepository
from graph_lineage.streamlit_ui.db.repository.experiment_repository import ExperimentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)


# Async helper functions
async def list_checkpoints_async(
    experiment_id: str | None = None, usable_only: bool = False
) -> list[dict]:
    """List checkpoints with parent experiment and used_by info."""
    db_client = get_neo4j_client()
    repo = CheckpointRepository(db_client)
    return await repo.list_all(experiment_id=experiment_id, usable_only=usable_only)


async def list_experiments_async() -> list[dict]:
    """List experiments for filter dropdown."""
    db_client = get_neo4j_client()
    repo = ExperimentRepository(db_client)
    return await repo.list_all()


async def update_uri_async(ckp_id: str, new_uri: str) -> dict:
    """Update checkpoint URI."""
    db_client = get_neo4j_client()
    repo = CheckpointRepository(db_client)
    return await repo.update_uri(ckp_id=ckp_id, new_uri=new_uri)


async def set_usable_async(ckp_id: str, is_usable: bool) -> dict:
    """Toggle checkpoint usability."""
    db_client = get_neo4j_client()
    repo = CheckpointRepository(db_client)
    return await repo.set_usable(ckp_id=ckp_id, is_usable=is_usable)


async def get_dependencies_async(ckp_id: str) -> list[dict]:
    """Get experiments that started from this checkpoint."""
    db_client = get_neo4j_client()
    repo = CheckpointRepository(db_client)
    return await repo.get_dependencies(ckp_id=ckp_id)


def run() -> None:
    """Run checkpoint management page."""
    st.title("Checkpoint Management")

    tab_browse, tab_uri_edit, tab_visibility = st.tabs(["Browse", "URI Edit", "Visibility"])

    with tab_browse:
        st.subheader("Browse Checkpoints")

        # Filter row
        col_exp, col_usable = st.columns([3, 1])
        with col_exp:
            try:
                experiments = run_async(list_experiments_async())
                exp_options = ["All"] + [e.get("exp_id", "") for e in experiments]
            except UIError:
                exp_options = ["All"]
            selected_exp = st.selectbox("Filter by experiment", exp_options)

        with col_usable:
            usable_only = st.checkbox("Usable only")

        try:
            exp_filter = None if selected_exp == "All" else selected_exp
            checkpoints = run_async(
                list_checkpoints_async(experiment_id=exp_filter, usable_only=usable_only)
            )

            if checkpoints:
                for ckp in checkpoints:
                    usable_badge = (
                        ":green[USABLE]" if ckp.get("is_usable", True)
                        else ":gray[HIDDEN]"
                    )
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2, 2, 1])
                        with col1:
                            st.markdown(f"**{ckp.get('ckp_id', 'N/A')}** {usable_badge}")
                            st.caption(
                                f"Epoch: {ckp.get('epoch', 'N/A')} | "
                                f"Run: {ckp.get('run', 'N/A')}"
                            )
                        with col2:
                            st.caption(f"URI: {ckp.get('uri', 'N/A')}")
                            st.caption(f"Parent: {ckp.get('parent_exp', 'N/A')}")
                        with col3:
                            used_by = ckp.get("used_by_exps", [])
                            used_count = len(used_by) if used_by else 0
                            st.caption(f"Used by: {used_count} experiment(s)")
                            st.caption(f"Created: {ckp.get('created_at', 'N/A')}")
            else:
                st.info("No checkpoints found")
                st.caption(
                    "Checkpoints are created automatically when training "
                    "completes successfully."
                )
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_uri_edit:
        st.subheader("Edit Checkpoint URI")
        try:
            checkpoints = run_async(list_checkpoints_async())

            if not checkpoints:
                st.info("No checkpoints available to edit.")
                return

            # Step 1: Select checkpoint
            ckp_ids = [c["ckp_id"] for c in checkpoints]
            selected_ckp = st.selectbox("Select checkpoint", ckp_ids, key="uri_edit_ckp")

            if selected_ckp:
                current = next((c for c in checkpoints if c["ckp_id"] == selected_ckp), None)
                if current:
                    # Step 2: Show current URI
                    current_uri = current.get("uri", "") or ""
                    st.text_input("Current URI", disabled=True, value=current_uri)

                    # Step 3: Input new URI
                    new_uri = st.text_input("New URI", key="new_uri_input")

                    # Step 4: Show dependencies
                    deps = run_async(get_dependencies_async(selected_ckp))
                    dep_count = len(deps) if deps else 0
                    st.info(
                        f"Dependencies: {dep_count} experiments started from this checkpoint"
                    )
                    if deps:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(deps))

                    # Step 5: Confirm and apply
                    if new_uri and new_uri != current_uri:
                        confirm = st.checkbox(
                            "I confirm this URI change",
                            key="confirm_uri_edit",
                        )
                        if confirm and st.button("Update URI"):
                            try:
                                run_async(update_uri_async(selected_ckp, new_uri))
                                st.success(f"URI updated for checkpoint {selected_ckp}.")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_visibility:
        st.subheader("Checkpoint Visibility")
        try:
            checkpoints = run_async(list_checkpoints_async())

            if not checkpoints:
                st.info("No checkpoints available.")
                return

            ckp_ids = [c["ckp_id"] for c in checkpoints]
            selected_ckp = st.selectbox("Select checkpoint", ckp_ids, key="vis_ckp")

            if selected_ckp:
                current = next((c for c in checkpoints if c["ckp_id"] == selected_ckp), None)
                if current:
                    is_usable = current.get("is_usable", True)

                    # Check dependencies
                    deps = run_async(get_dependencies_async(selected_ckp))
                    dep_count = len(deps) if deps else 0

                    if is_usable is not False:
                        st.markdown("**Current status:** Usable")

                        if dep_count > 0:
                            st.warning(
                                f"{dep_count} experiments use this checkpoint "
                                "as a starting point."
                            )

                        confirm = st.checkbox(
                            "I understand dependent experiments may be affected",
                            key="confirm_hide_ckp",
                        )
                        if confirm and st.button("Hide Checkpoint"):
                            try:
                                run_async(set_usable_async(selected_ckp, False))
                                st.success(f"Checkpoint {selected_ckp} hidden.")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
                    else:
                        st.markdown("**Current status:** :gray[HIDDEN]")
                        if st.button("Restore Checkpoint"):
                            try:
                                run_async(set_usable_async(selected_ckp, True))
                                st.success(f"Checkpoint {selected_ckp} restored.")
                            except UIError as e:
                                st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")
