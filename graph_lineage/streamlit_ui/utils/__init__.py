"""Caching utilities for Streamlit UI."""

from __future__ import annotations

import streamlit as st

from graph_lineage.streamlit_ui.utils.api_client import HTTPXClient
from graph_lineage.streamlit_ui.config import Config


@st.cache_resource
def get_config() -> Config:
    """Get or cache Config instance."""
    return Config()

@st.cache_resource
def get_api_client() -> HTTPXClient:
    """Return a cached HTTPXClient instance (constructed synchronously)."""
    config = get_config()
    return HTTPXClient(
        base_url=config.master_api_url,
        api_token=config.master_api_token,
    )

