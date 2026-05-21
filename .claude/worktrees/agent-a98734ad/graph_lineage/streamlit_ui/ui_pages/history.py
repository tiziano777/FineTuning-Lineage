"""History page -- navigate, rollback, and squash experiment chains."""

from __future__ import annotations

import logging

import streamlit as st

from graph_lineage.history.repository import ExperimentRepository as HistoryRepository
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async

logger = logging.getLogger(__name__)


async def _get_experiment_ids(db_client) -> list[str]:
    """Fetch all experiment IDs for selection dropdowns."""
    records = await db_client.run_list(
        "MATCH (e:Experiment) RETURN e.exp_id AS exp_id ORDER BY e.created_at DESC LIMIT 100"
    )
    return [r["exp_id"] for r in records if r.get("exp_id")]


def _render_navigate_tab(history_repo: HistoryRepository, experiment_ids: list[str]) -> None:
    """Render the Navigate tab (US-8): back/forward through experiment chain."""
    if not experiment_ids:
        st.info("No history available")
        st.caption("Run experiments to build a history chain that you can navigate.")
        return

    selected_exp = st.selectbox(
        "Select experiment",
        experiment_ids,
        key="nav_experiment",
    )

    col_back, col_forward = st.columns(2)

    with col_back:
        if st.button("Back", key="nav_back"):
            try:
                result = run_async(history_repo.navigate_back(selected_exp, steps=1))
                st.session_state["nav_result"] = result
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Navigation failed: {e}")
                logger.exception("navigate_back failed")

    with col_forward:
        if st.button("Forward", key="nav_forward"):
            try:
                result = run_async(history_repo.navigate_forward(selected_exp, steps=1))
                st.session_state["nav_result"] = result
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Navigation failed: {e}")
                logger.exception("navigate_forward failed")

    # Display navigation result
    nav_result = st.session_state.get("nav_result")
    if nav_result:
        st.divider()
        st.subheader("Current Position")
        summary = nav_result.summary
        st.write(f"**Experiment:** {summary.exp_id}")
        st.write(f"**Status:** {summary.status}")
        st.write(f"**Description:** {summary.description}")
        st.caption(f"Strategy: {summary.strategy} | Checkpoints: {summary.checkpoint_count}")

        if nav_result.codebase:
            with st.expander("Reconstructed Codebase"):
                for filename, content in nav_result.codebase.items():
                    st.caption(filename)
                    st.code(content, language="python")


def _render_rollback_tab(history_repo: HistoryRepository, experiment_ids: list[str]) -> None:
    """Render the Rollback tab (US-9): preview and apply rollback wizard."""
    if not experiment_ids:
        st.info("No history available")
        st.caption("Run experiments to build a history chain that you can navigate.")
        return

    # Step 1: Select experiment
    selected_exp = st.selectbox(
        "Select experiment to rollback to",
        experiment_ids,
        key="rollback_experiment",
    )

    # Step 2: Preview
    if st.button("Preview Rollback", key="preview_rollback"):
        try:
            preview = run_async(history_repo.preview_rollback(selected_exp))
            st.session_state["rollback_preview"] = preview
        except ValueError as e:
            st.warning(str(e))
        except Exception as e:
            st.error(f"Preview failed: {e}")
            logger.exception("preview_rollback failed")

    preview = st.session_state.get("rollback_preview")
    if preview:
        st.divider()
        st.subheader("Preview")

        st.write(f"**Target:** {preview.target_exp_id}")
        st.write(f"**Experiments affected:** {preview.total_experiments}")
        st.write(f"**Checkpoints affected:** {preview.total_checkpoints}")

        if preview.branch_count > 0:
            st.warning(f"This rollback would orphan {preview.branch_count} branch(es). Force required.")

        if preview.warning:
            st.warning(preview.warning)

        # Show affected experiments
        if preview.affected_experiments:
            with st.expander("Affected Experiments"):
                for exp_summary in preview.affected_experiments:
                    st.write(f"- **{exp_summary.exp_id}** ({exp_summary.status}) -- {exp_summary.description}")

        st.caption("Experiments after this point will be hidden (usable=false)")

        # Step 3: Confirm and apply
        confirmed = st.checkbox("I have reviewed the changes above", key="confirm_rollback")

        force = False
        if preview.branch_count > 0:
            force = st.checkbox("Force rollback (orphan branches)", key="force_rollback")

        if confirmed and st.button("Apply Rollback", key="apply_rollback"):
            try:
                run_async(history_repo.apply_rollback(preview, force=force))
                st.success("Rollback applied successfully")
                # Clear preview state
                del st.session_state["rollback_preview"]
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Rollback failed: {e}")
                logger.exception("apply_rollback failed")


def _render_squash_tab(history_repo: HistoryRepository, experiment_ids: list[str]) -> None:
    """Render the Squash tab (US-10): preview and confirm squash wizard."""
    if not experiment_ids:
        st.info("No history available")
        st.caption("Run experiments to build a history chain that you can navigate.")
        return

    # Step 1: Select range
    col_from, col_to = st.columns(2)
    with col_from:
        from_exp = st.selectbox("From experiment", experiment_ids, key="squash_from")
    with col_to:
        to_exp = st.selectbox("To experiment", experiment_ids, key="squash_to")

    if from_exp == to_exp:
        st.caption("Select different experiments to define a squash range.")
        return

    # Step 2: Preview
    st.divider()
    st.subheader("Squash Preview")
    st.write(f"Squashing chain from **{from_exp}** to **{to_exp}**")
    st.write("Intermediate experiments will be deleted and replaced with a single cumulative diff.")

    # Step 3: Warning and confirm
    st.warning("This will merge experiments into a single node. This cannot be undone.")

    confirmed = st.checkbox("I have reviewed the squash preview", key="confirm_squash")

    if confirmed and st.button("Confirm Squash", key="apply_squash"):
        try:
            run_async(history_repo.squash_chain(from_exp, to_exp))
            st.success("Squash completed")
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Squash failed: {e}")
            logger.exception("squash_chain failed")


def run() -> None:
    """Run history page."""
    st.title("History")

    db_client = get_neo4j_client()
    history_repo = HistoryRepository(db_client)

    try:
        experiment_ids = run_async(_get_experiment_ids(db_client))
    except Exception as e:
        st.error("Cannot connect to Neo4j. Check that the database is running and connection settings are correct.")
        logger.exception("Failed to fetch experiment IDs")
        return

    tab_navigate, tab_rollback, tab_squash = st.tabs(["Navigate", "Rollback", "Squash"])

    with tab_navigate:
        _render_navigate_tab(history_repo, experiment_ids)

    with tab_rollback:
        _render_rollback_tab(history_repo, experiment_ids)

    with tab_squash:
        _render_squash_tab(history_repo, experiment_ids)
