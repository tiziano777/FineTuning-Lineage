"""In-memory Neo4j mock for testing lineage system.

Provides InMemoryNeo4jTracker that tracks all node and edge operations,
enabling queryable state for test assertions without requiring a real database.
"""

from __future__ import annotations

from typing import Any
from datetime import datetime
from uuid import uuid4

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.data_classes.neo4j.nodes.checkpoint import Checkpoint


class InMemoryNeo4jTracker:
    """In-memory Neo4j mock that tracks node and edge creation.

    Stores experiments, checkpoints, and relationships in memory.
    Provides CRUD methods matching graph_lineage.lineage.neo4j_ops signatures.
    Provides query/inspection methods for test assertions.
    """

    def __init__(self):
        """Initialize empty tracker."""
        self.experiments: dict[str, dict[str, Any]] = {}  # id -> experiment dict
        self.checkpoints: dict[str, dict[str, Any]] = {}  # id -> checkpoint dict
        self.edges: list[tuple[str, str, str, dict[str, Any]]] = []  # (from_id, to_id, rel_type, props)

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD Methods (match neo4j_ops.py signatures)
    # ─────────────────────────────────────────────────────────────────────────

    def create_experiment_node(self, exp: Experiment) -> str:
        """Create an experiment node and store it.

        Args:
            exp: Experiment instance

        Returns:
            The experiment ID
        """
        exp_dict = exp.model_dump()
        self.experiments[exp.id] = exp_dict
        return exp.id

    def find_experiment_by_id(self, experiment_id: str) -> Experiment | None:
        """Find experiment by ID.

        Args:
            experiment_id: UUID of experiment

        Returns:
            Experiment instance if found, None otherwise
        """
        if experiment_id in self.experiments:
            return Experiment.model_validate(self.experiments[experiment_id])
        return None

    def find_parent_experiment(self, uri: str) -> Experiment | None:
        """Find most recent experiment by URI.

        Args:
            uri: Project URI to search for

        Returns:
            Most recent Experiment with this URI, None if not found
        """
        candidates = [
            exp_dict
            for exp_dict in self.experiments.values()
            if exp_dict.get("uri") == uri
        ]
        if candidates:
            # Sort by created_at descending and get the most recent
            most_recent = max(
                candidates,
                key=lambda x: x.get("created_at", "")
            )
            return Experiment.model_validate(most_recent)
        return None

    def create_checkpoint_node(self, ckp: Checkpoint) -> str:
        """Create a checkpoint node and store it.

        Args:
            ckp: Checkpoint instance

        Returns:
            The checkpoint ID
        """
        ckp_dict = ckp.model_dump()
        self.checkpoints[ckp.id] = ckp_dict
        return ckp.id

    def create_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a relationship edge.

        Args:
            from_id: Source node ID
            to_id: Target node ID
            rel_type: Relationship type (DERIVED_FROM, RETRY_OF, STARTED_FROM, PRODUCED)
            properties: Optional properties dict
        """
        self.edges.append((from_id, to_id, rel_type, properties or {}))

    def create_checkpoint_edge(self, exp_id: str, ckp_id: str) -> None:
        """Create PRODUCED edge from experiment to checkpoint.

        Args:
            exp_id: Experiment ID
            ckp_id: Checkpoint ID
        """
        self.create_edge(exp_id, ckp_id, "PRODUCED")

    def update_experiment_status(
        self,
        exp_id: str = None,
        experiment_id: str = None,
        status: str = None,
        exit_msg: str | None = None,
        exit_message: str | None = None,
        metrics_uri: str | None = None,
    ) -> None:
        """Update experiment status and optional fields.

        Args:
            exp_id or experiment_id: UUID of experiment
            status: New status (RUNNING, COMPLETED, FAILED)
            exit_msg or exit_message: Optional exit/error message
            metrics_uri: Optional URI to metrics data
        """
        # Handle both parameter names (server uses exp_id, client might use experiment_id)
        eid = exp_id or experiment_id
        msg = exit_msg or exit_message

        if eid in self.experiments:
            self.experiments[eid]["status"] = status
            if msg is not None:
                self.experiments[eid]["exit_message"] = msg
            if metrics_uri is not None:
                self.experiments[eid]["metrics_uri"] = metrics_uri
            self.experiments[eid]["updated_at"] = datetime.utcnow()

    # ─────────────────────────────────────────────────────────────────────────
    # Query/Inspection Methods (for test assertions)
    # ─────────────────────────────────────────────────────────────────────────

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        """Get raw experiment data for inspection.

        Args:
            experiment_id: UUID of experiment

        Returns:
            Raw experiment dict if found, None otherwise
        """
        return self.experiments.get(experiment_id)

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Get raw checkpoint data for inspection.

        Args:
            checkpoint_id: UUID of checkpoint

        Returns:
            Raw checkpoint dict if found, None otherwise
        """
        return self.checkpoints.get(checkpoint_id)

    def get_all_experiments(self) -> dict[str, dict[str, Any]]:
        """Get all experiments.

        Returns:
            Dict mapping experiment IDs to experiment dicts
        """
        return dict(self.experiments)

    def get_all_checkpoints(self) -> dict[str, dict[str, Any]]:
        """Get all checkpoints.

        Returns:
            Dict mapping checkpoint IDs to checkpoint dicts
        """
        return dict(self.checkpoints)

    def get_edges_from(self, from_id: str) -> list[tuple[str, str, str, dict]]:
        """Get all edges originating from a node.

        Args:
            from_id: Source node ID

        Returns:
            List of (from_id, to_id, rel_type, props) tuples
        """
        return [
            (f, t, r, p) for f, t, r, p in self.edges if f == from_id
        ]

    def get_edges_to(self, to_id: str) -> list[tuple[str, str, str, dict]]:
        """Get all edges targeting a node.

        Args:
            to_id: Target node ID

        Returns:
            List of (from_id, to_id, rel_type, props) tuples
        """
        return [
            (f, t, r, p) for f, t, r, p in self.edges if t == to_id
        ]

    def get_edges_of_type(self, rel_type: str) -> list[tuple[str, str, str, dict]]:
        """Get all edges of a specific type.

        Args:
            rel_type: Relationship type (DERIVED_FROM, RETRY_OF, STARTED_FROM, PRODUCED)

        Returns:
            List of (from_id, to_id, rel_type, props) tuples
        """
        return [
            (f, t, r, p) for f, t, r, p in self.edges if r == rel_type
        ]

    def get_all_edges(self) -> list[tuple[str, str, str, dict]]:
        """Get all edges.

        Returns:
            List of (from_id, to_id, rel_type, props) tuples
        """
        return list(self.edges)

    # ─────────────────────────────────────────────────────────────────────────
    # Assertion Helpers (for clear test failures)
    # ─────────────────────────────────────────────────────────────────────────

    def assert_experiment_created(
        self,
        experiment_id: str,
        strategy: str | None = None,
        status: str | None = None,
        base: bool | None = None,
    ) -> None:
        """Assert experiment exists with expected properties.

        Args:
            experiment_id: UUID to check
            strategy: Expected strategy if specified
            status: Expected status if specified
            base: Expected base flag if specified

        Raises:
            AssertionError if conditions not met
        """
        assert experiment_id in self.experiments, (
            f"Experiment {experiment_id} not created"
        )
        exp = self.experiments[experiment_id]

        if strategy is not None:
            assert exp.get("strategy") == strategy, (
                f"Expected strategy {strategy}, got {exp.get('strategy')}"
            )
        if status is not None:
            assert exp.get("status") == status, (
                f"Expected status {status}, got {exp.get('status')}"
            )
        if base is not None:
            assert exp.get("base") == base, (
                f"Expected base {base}, got {exp.get('base')}"
            )

    def assert_edge_exists(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
    ) -> None:
        """Assert an edge exists between two nodes.

        Args:
            from_id: Source node ID
            to_id: Target node ID
            rel_type: Expected relationship type

        Raises:
            AssertionError if edge not found
        """
        found = any(
            f == from_id and t == to_id and r == rel_type
            for f, t, r, _ in self.edges
        )
        assert found, (
            f"Edge {from_id} -{rel_type}-> {to_id} not found. "
            f"Available edges: {self.edges}"
        )

    def assert_edge_not_exists(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
    ) -> None:
        """Assert an edge does NOT exist between two nodes.

        Args:
            from_id: Source node ID
            to_id: Target node ID
            rel_type: Relationship type

        Raises:
            AssertionError if edge found
        """
        found = any(
            f == from_id and t == to_id and r == rel_type
            for f, t, r, _ in self.edges
        )
        assert not found, (
            f"Unexpected edge {from_id} -{rel_type}-> {to_id} was created"
        )

    def assert_experiment_count(self, expected: int) -> None:
        """Assert total number of experiments created.

        Args:
            expected: Expected count

        Raises:
            AssertionError if count doesn't match
        """
        actual = len(self.experiments)
        assert actual == expected, (
            f"Expected {expected} experiments, got {actual}"
        )

    def assert_checkpoint_count(self, expected: int) -> None:
        """Assert total number of checkpoints created.

        Args:
            expected: Expected count

        Raises:
            AssertionError if count doesn't match
        """
        actual = len(self.checkpoints)
        assert actual == expected, (
            f"Expected {expected} checkpoints, got {actual}"
        )

    def assert_edges_count_of_type(self, rel_type: str, expected: int) -> None:
        """Assert number of edges of a specific type.

        Args:
            rel_type: Relationship type to count
            expected: Expected count

        Raises:
            AssertionError if count doesn't match
        """
        edges = self.get_edges_of_type(rel_type)
        assert len(edges) == expected, (
            f"Expected {expected} edges of type {rel_type}, got {len(edges)}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all stored data (for test isolation)."""
        self.experiments.clear()
        self.checkpoints.clear()
        self.edges.clear()

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"InMemoryNeo4jTracker("
            f"experiments={len(self.experiments)}, "
            f"checkpoints={len(self.checkpoints)}, "
            f"edges={len(self.edges)}"
            f")"
        )
