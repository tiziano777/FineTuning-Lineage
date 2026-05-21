"""Configuration module for Streamlit UI."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration from environment variables."""

    master_api_url: str = os.getenv("MASTER_API_URL", "http://localhost:8000")
    neo4j_uri: str = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "password")
    master_api_token: str = os.getenv("MASTER_API_TOKEN", "")
    streamlit_theme: dict = None

    def __post_init__(self) -> None:
        """Initialize theme colors."""
        if self.streamlit_theme is None:
            self.streamlit_theme = {
                "primaryColor": "#FF6B6B",
                "backgroundColor": "#0E1117",
                "secondaryBackgroundColor": "#262730",
                "textColor": "#FAFAFA",
            }
