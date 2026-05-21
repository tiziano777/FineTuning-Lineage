"""Admin console page with integrity checks on experiment data."""

from __future__ import annotations

import logging

import streamlit as st

from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async

logger = logging.getLogger(__name__)

# -- Integrity check queries ------------------------------------------------

_QUERY_MISSING_USES_MODEL = """
MATCH (e:Experiment)
WHERE NOT EXISTS((e)-[:USES_MODEL]->())
RETURN e.exp_id AS exp_id, e.status AS status
"""

_QUERY_MISSING_USES_RECIPE = """
MATCH (e:Experiment)
WHERE NOT EXISTS((e)-[:USES_RECIPE]->())
RETURN e.exp_id AS exp_id, e.status AS status
"""

_QUERY_STALE_RUNNING = """
MATCH (e:Experiment {status: 'RUNNING'})
WHERE e.created_at < datetime() - duration('PT24H')
RETURN e.exp_id AS exp_id, e.created_at AS created_at
"""

_QUERY_DUPLICATE_CONFIG_HASH = """
MATCH (e1:Experiment), (e2:Experiment)
WHERE e1.config_hash = e2.config_hash AND e1.exp_id < e2.exp_id
AND NOT EXISTS((e2)-[:RETRY_FROM]->(e1))
AND NOT EXISTS((e1)-[:RETRY_FROM]->(e2))
RETURN e1.exp_id AS exp1, e2.exp_id AS exp2, e1.config_hash AS config_hash
"""

_QUERY_CYCLE_DETECTION = """
MATCH path = (e:Experiment)-[:DERIVED_FROM|RETRY_FROM*]->(e)
RETURN COUNT(path) AS cycles
"""

# -- Check definitions ------------------------------------------------------

_CHECKS: list[tuple[str, str]] = [
    ("Experiments without USES_MODEL", _QUERY_MISSING_USES_MODEL),
    ("Experiments without USES_RECIPE", _QUERY_MISSING_USES_RECIPE),
    ("Stale RUNNING experiments (>24h)", _QUERY_STALE_RUNNING),
    ("Duplicate config_hash without RETRY_FROM", _QUERY_DUPLICATE_CONFIG_HASH),
    ("Cycle detection (DERIVED_FROM / RETRY_FROM)", _QUERY_CYCLE_DETECTION),
]


# -- Page entry point -------------------------------------------------------


def run() -> None:
    """Run admin console page."""
    st.title("Admin Console")

    if st.button("Run Check", type="primary"):
        db_client = get_neo4j_client()
        all_passed = True

        for check_name, cypher in _CHECKS:
            with st.expander(check_name, expanded=True):
                try:
                    if check_name.startswith("Cycle detection"):
                        record = run_async(db_client.run_single(cypher))
                        cycle_count = record["cycles"] if record else 0
                        if cycle_count == 0:
                            st.success("Passed")
                        else:
                            all_passed = False
                            st.warning(f"Found {cycle_count} cycle(s)")
                    else:
                        results = run_async(db_client.run_list(cypher))
                        if not results:
                            st.success("Passed")
                        else:
                            all_passed = False
                            st.warning(f"Found {len(results)} issue(s)")
                            st.dataframe(results)
                except Exception:
                    logger.exception("Integrity check failed: %s", check_name)
                    all_passed = False
                    st.error(f"Check failed: {check_name}")

        if all_passed:
            st.success("All checks passed")
            st.caption("No consistency issues detected.")
