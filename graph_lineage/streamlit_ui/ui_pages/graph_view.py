"""Graph visualization page -- experiment lineage DAG using streamlit-agraph."""

from __future__ import annotations

import logging

import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError

logger = logging.getLogger(__name__)

# -- Status color mapping per UI-SPEC --
_STATUS_COLORS = {
    "COMPLETED": "#68BF40",
    "RUNNING": "#F9A825",
    "FAILED": "#D32F2F",
}
_HIDDEN_COLOR = "#BDBDBD"
_CHECKPOINT_COLOR = "#42A5F5"
_SECONDARY_COLOR = "#E8E8E0"

# -- Edge label mapping --
_EDGE_LABELS = {
    "DERIVED_FROM": "derived",
    "RETRY_FROM": "retry",
    "RETRY_OF": "retry",
    "STARTED_FROM": "resumed",
    "PRODUCED_BY": "produced",
    "MERGED_FROM": "merged",
}


async def fetch_lineage_graph(db_client, root_exp_id: str | None = None) -> dict:
    """Fetch experiments, checkpoints, and their relationships for graph rendering.

    Returns dict with 'nodes' and 'edges' lists ready for agraph.
    """
    # Build experiment query with optional filter
    if root_exp_id and root_exp_id != "All":
        query = """
        MATCH (e:Experiment {exp_id: $exp_id})
        OPTIONAL MATCH path = (e)<-[:DERIVED_FROM|RETRY_FROM*0..50]-(desc:Experiment)
        OPTIONAL MATCH path2 = (e)-[:DERIVED_FROM|RETRY_FROM*0..50]->(anc:Experiment)
        WITH COLLECT(DISTINCT desc) + COLLECT(DISTINCT anc) + [e] AS all_exps
        UNWIND all_exps AS exp
        WITH DISTINCT exp
        OPTIONAL MATCH (exp)-[r:DERIVED_FROM|RETRY_FROM|STARTED_FROM|MERGED_FROM]->(target)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(exp)
        RETURN exp.exp_id AS exp_id, exp.status AS status,
               exp.description AS description, exp.usable AS usable,
               type(r) AS rel_type, target.exp_id AS target_exp_id,
               COLLECT(DISTINCT ckp.ckp_id) AS checkpoint_ids
        """
        records = await db_client.run_list(query, exp_id=root_exp_id)
    else:
        query = """
        MATCH (e:Experiment)
        OPTIONAL MATCH (e)-[r:DERIVED_FROM|RETRY_FROM|STARTED_FROM|MERGED_FROM]->(target)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
        RETURN e.exp_id AS exp_id, e.status AS status,
               e.description AS description, e.usable AS usable,
               type(r) AS rel_type, target.exp_id AS target_exp_id,
               COLLECT(DISTINCT ckp.ckp_id) AS checkpoint_ids
        LIMIT 100
        """
        records = await db_client.run_list(query)

    # Process into unique nodes and edges
    seen_nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    for record in records:
        exp_id = record["exp_id"]
        if not exp_id:
            continue

        # Build experiment node
        if exp_id not in seen_nodes:
            usable = record.get("usable", True)
            status = record.get("status", "") or ""
            if not usable:
                color = _HIDDEN_COLOR
            else:
                color = _STATUS_COLORS.get(status.upper(), _SECONDARY_COLOR)

            label = exp_id
            if record.get("description"):
                label = f"{exp_id}\n{record['description'][:30]}"

            seen_nodes[exp_id] = Node(
                id=exp_id,
                label=label,
                size=25,
                color=color,
                shape="dot",
            )

        # Build checkpoint nodes
        for ckp_id in record.get("checkpoint_ids", []):
            if ckp_id and ckp_id not in seen_nodes:
                seen_nodes[ckp_id] = Node(
                    id=ckp_id,
                    label=ckp_id,
                    size=15,
                    color=_CHECKPOINT_COLOR,
                    shape="diamond",
                )
                edges.append(Edge(
                    source=ckp_id,
                    target=exp_id,
                    label="produced",
                ))

        # Build relationship edge
        rel_type = record.get("rel_type")
        target_id = record.get("target_exp_id")
        if rel_type and target_id:
            edge_label = _EDGE_LABELS.get(rel_type, rel_type)
            edges.append(Edge(
                source=exp_id,
                target=target_id,
                label=edge_label,
            ))

    return {"nodes": list(seen_nodes.values()), "edges": edges}


async def _get_experiment_ids(db_client) -> list[str]:
    """Fetch all experiment IDs for the selector dropdown."""
    records = await db_client.run_list(
        "MATCH (e:Experiment) RETURN e.exp_id AS exp_id ORDER BY e.created_at DESC LIMIT 100"
    )
    return [r["exp_id"] for r in records if r.get("exp_id")]


def run() -> None:
    """Run graph visualization page."""
    st.title("Graph View")

    db_client = get_neo4j_client()

    try:
        experiment_ids = run_async(_get_experiment_ids(db_client))
    except Exception as e:
        st.error(f"Cannot connect to Neo4j. Check that the database is running and connection settings are correct.")
        logger.exception("Failed to fetch experiment IDs")
        return

    if not experiment_ids:
        st.info(
            "No experiment selected",
            icon=":material/info:",
        )
        st.caption("Select an experiment from the dropdown to visualize its lineage chain.")
        return

    selected = st.selectbox(
        "Select experiment (or view all)",
        ["All"] + experiment_ids,
    )

    try:
        graph_data = run_async(fetch_lineage_graph(db_client, selected))
    except UIError as e:
        st.error(f"Error: {e.user_message}")
        return
    except Exception as e:
        st.error(f"Unexpected error loading graph: {e}")
        logger.exception("Graph fetch failed")
        return

    nodes = graph_data["nodes"]
    edges = graph_data["edges"]

    if not nodes:
        st.info("No experiment selected")
        st.caption("Select an experiment from the dropdown to visualize its lineage chain.")
        return

    st.caption(f"Showing {len(nodes)} nodes, {len(edges)} edges")

    config = Config(
        width=800,
        height=600,
        directed=True,
        physics=True,
        hierarchical=Config.Hierarchical(
            enabled=True,
            direction="UD",
            sortMethod="directed",
        ),
    )

    agraph(nodes=nodes, edges=edges, config=config)
