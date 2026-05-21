"""Utility formatters for Streamlit UI."""

from __future__ import annotations

from typing import Any


def format_recipe_table(recipes: list[dict]) -> dict:
    """Format recipe data for Streamlit dataframe display.

    Args:
        recipes: List of recipe dictionaries.

    Returns:
        Dict suitable for st.dataframe().
    """
    return {
        "Name": [r.get("name", "N/A") for r in recipes],
        "Framework": [r.get("framework", "N/A") for r in recipes],
        "Stage": [r.get("stage", "N/A") for r in recipes],
        "Created": [r.get("created_at", "N/A") for r in recipes],
    }


def format_model_table(models: list[dict]) -> dict:
    """Format model data for dataframe display.

    Args:
        models: List of model dictionaries.

    Returns:
        Dict suitable for st.dataframe().
    """
    return {
        "Name": [m.get("model_name", "N/A") for m in models],
        "Framework": [m.get("framework", "N/A") for m in models],
        "Version": [m.get("version", "N/A") for m in models],
        "Created": [m.get("created_at", "N/A") for m in models],
    }


def format_component_table(components: list[dict]) -> dict:
    """Format component data for dataframe display.

    Args:
        components: List of component dictionaries.

    Returns:
        Dict suitable for st.dataframe().
    """
    return {
        "Opt Code": [c.get("opt_code", "N/A") for c in components],
        "Technique": [c.get("technique_code", "N/A") for c in components],
        "Framework": [c.get("framework_code", "N/A") for c in components],
        "Created": [c.get("created_at", "N/A") for c in components],
    }


def format_experiment_table(experiments: list[dict]) -> dict:
    """Format experiment data for dataframe display.

    Args:
        experiments: List of experiment dictionaries.

    Returns:
        Dict suitable for st.dataframe().
    """
    return {
        "Name": [e.get("exp_id", "N/A") for e in experiments],
        "Status": [e.get("status", "N/A") for e in experiments],
        "Created": [e.get("created_at", "N/A") for e in experiments],
    }
