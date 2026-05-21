"""Streamlit Master UI main application."""

from __future__ import annotations

import asyncio
import atexit
import os
from pathlib import Path

import streamlit as st

from graph_lineage.streamlit_ui.utils import get_api_client, get_config, get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async


async def ensure_schema_initialized() -> None:
    """Execute Neo4j schema initialization scripts (idempotent).

    Runs Cypher DDL files in order:
      1. 01-schema.cypher — Node types, constraints, indexes
      2. 02-triggers.cypher — APOC triggers for automation

    Safe to call multiple times; subsequent runs are no-ops for existing constraints.
    Uses CREATE ... IF NOT EXISTS patterns for idempotency.
    """
    try:
        db_client = get_neo4j_client()

        # Schema files to load in order
        schema_files = [
            "01-schema.cypher",
            "02-triggers.cypher"
        ]

        base_path = Path(__file__).parent.parent  / "neo4j_client"

        for schema_file_name in schema_files:
            schema_file = base_path / schema_file_name
            if not schema_file.exists():
                st.warning(f"Schema file not found: {schema_file}")
                continue

            with open(schema_file) as f:
                cypher_content = f.read()

            # Split by semicolon and execute each command
            commands_executed = 0
            for command in cypher_content.split(";"):
                command = command.strip()
                # Skip empty lines and comments
                if command and not command.startswith("//"):
                    try:
                        await db_client.run(command)
                        commands_executed += 1
                    except Exception as cmd_error:
                        # Log but continue — idempotent operations may fail gracefully
                        print(f"Cypher command warning in {schema_file_name}: {cmd_error}")

            if commands_executed > 0:
                print(f"Loaded {schema_file_name}: {commands_executed} commands executed")

        st.session_state.schema_initialized = True
    except Exception as e:
        st.warning(f"Schema initialization warning (non-fatal): {e}")


def main() -> None:
    """Main Streamlit app entry point."""
    st.set_page_config(
        page_title="FineTuning Envelope Master",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Register cleanup handler once per session
    if "cleanup_registered" not in st.session_state:
        atexit.register(cleanup_resources)
        st.session_state.cleanup_registered = True

    # Initialize session state
    if "config" not in st.session_state:
        st.session_state.config = get_config()

    if "api_token" not in st.session_state:
        st.session_state.api_token = os.getenv("MASTER_API_TOKEN", "")

    if "current_page" not in st.session_state:
        st.session_state.current_page = "Recipes"

    # Initialize Neo4j schema (only happens once per session)
    if "schema_initialized" not in st.session_state:
        run_async(ensure_schema_initialized())

    # Sidebar navigation
    st.sidebar.title("FineTuning Envelope")


    # Page selection with grouped navigation
    st.sidebar.subheader("Entities")
    entity_pages = ["Models", "Recipes", "Components", "Experiments", "Checkpoints"]
    st.sidebar.markdown("---")
    st.sidebar.subheader("Visualization")
    viz_pages = ["Graph View", "History"]
    st.sidebar.markdown("---")
    st.sidebar.subheader("Admin")
    admin_pages = ["Admin Console"]
    page_options = entity_pages + viz_pages + admin_pages

    # Ensure current_page is valid for new page list
    if st.session_state.current_page not in page_options:
        st.session_state.current_page = "Models"

    page = st.sidebar.radio(
        "Navigate",
        page_options,
        index=page_options.index(st.session_state.current_page),
        label_visibility="collapsed",
    )

    # Update session state when page changes
    st.session_state.current_page = page

    # Dynamic page loading
    try:
        if page == "Recipes":
            from graph_lineage.streamlit_ui.ui_pages import recipes
            recipes.run()
        elif page == "Models":
            from graph_lineage.streamlit_ui.ui_pages import models
            models.run()
        elif page == "Experiments":
            from graph_lineage.streamlit_ui.ui_pages import experiments
            experiments.run()
        elif page == "Components":
            from graph_lineage.streamlit_ui.ui_pages import components
            components.run()
        elif page == "Checkpoints":
            from graph_lineage.streamlit_ui.ui_pages import checkpoints
            checkpoints.run()
        elif page == "Graph View":
            from graph_lineage.streamlit_ui.ui_pages import graph_view
            graph_view.run()
        elif page == "History":
            from graph_lineage.streamlit_ui.ui_pages import history
            history.run()
        elif page == "Admin Console":
            from graph_lineage.streamlit_ui.ui_pages import admin
            admin.run()
    except Exception as e:
        st.error(f"Error loading page: {str(e)}")
        st.exception(e)

    # Footer
    st.sidebar.divider()
    st.sidebar.caption(f"API: {st.session_state.config.master_api_url}")
    st.sidebar.caption(f"Neo4j: {st.session_state.config.neo4j_uri}")


def cleanup_resources() -> None:
    """Cleanup database and API connections on app exit.

    Called via atexit handler to ensure resources are released when the Streamlit
    process terminates. This prevents connection pool exhaustion and ensures
    proper shutdown of async clients.
    """
    try:
        api_client = get_api_client()
        db_client = get_neo4j_client()

        # Create a temporary event loop for cleanup (we're in shutdown phase)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Close both clients gracefully
        loop.run_until_complete(api_client.close())
        loop.run_until_complete(db_client.close())

        loop.close()
    except Exception:
        # Silently ignore errors during shutdown - don't raise exceptions in teardown
        pass


if __name__ == "__main__":
    main()
