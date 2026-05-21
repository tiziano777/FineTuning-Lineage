"""Caching utilities for Streamlit UI."""

from __future__ import annotations

import streamlit as st

from graph_lineage.streamlit_ui.utils.api_client import HTTPXClient
from graph_lineage.streamlit_ui.config import Config
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient


@st.cache_resource
def get_config() -> Config:
    """Get or cache Config instance."""
    return Config()


@st.cache_resource
def get_neo4j_client() -> AsyncNeo4jClient:
    """Return a cached AsyncNeo4jClient instance (constructed synchronously)."""
    config = get_config()
    return AsyncNeo4jClient(
        uri=config.neo4j_uri,
        user=config.neo4j_user,
        password=config.neo4j_password,
    )


@st.cache_resource
def get_api_client() -> HTTPXClient:
    """Return a cached HTTPXClient instance (constructed synchronously)."""
    config = get_config()
    return HTTPXClient(
        base_url=config.master_api_url,
        api_token=config.master_api_token,
    )

