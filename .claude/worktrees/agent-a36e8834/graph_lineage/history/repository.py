"""ExperimentRepository: history management and graph navigation operations."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from graph_lineage.diff.reconstructor import reconstruct_codebase
from graph_lineage.diff.differ import compute_snapshot_diff
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.history.models import (
    CheckpointSummary,
    ExperimentSummary,
    NavigationResult,
    RollbackPreview,
)


class Neo4jClient(Protocol):
    """Protocol for async Neo4j client -- avoids direct import of neo4j_async."""

    async def run(self, query: str, **kwargs: Any) -> Any: ...
    async def run_single(self, query: str, **kwargs: Any) -> Optional[dict]: ...
    async def run_list(self, query: str, **kwargs: Any) -> list[dict]: ...


def _build_experiment_summary(record: dict[str, Any]) -> ExperimentSummary:
    """Build ExperimentSummary from a Neo4j record containing exp + ckps."""
    ckps_raw = record.get("checkpoints", [])
    checkpoints = [
        CheckpointSummary(
            ckp_id=c["ckp_id"],
            epoch=c.get("epoch", 0),
            run=c.get("run", 0),
            metrics_snapshot=c.get("metrics_snapshot", {}),
            uri=c.get("uri"),
            is_usable=c.get("is_usable", True),
        )
        for c in ckps_raw
    ]
    return ExperimentSummary(
        exp_id=record["exp_id"],
        description=record.get("description", ""),
        status=record.get("status", ""),
        strategy=record.get("strategy", ""),
        usable=record.get("usable", True),
        config_hash=record.get("config_hash", ""),
        created_at=str(record["created_at"]) if record.get("created_at") else None,
        checkpoint_count=len(checkpoints),
        checkpoints=checkpoints,
    )


class ExperimentRepository:
    """History management operations on the experiment lineage graph.

    All methods are async and delegate to AsyncNeo4jClient for Neo4j access.
    """

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    # -- 1. Reconstruct codebase at any experiment --

    async def reconstruct_at(self, target_exp_id: str) -> dict[str, str]:
        """Reconstruct full codebase state at a given experiment.

        Traverses DERIVED_FROM chain back to the base experiment,
        collects codebase snapshots/diffs, and applies them sequentially.

        Raises:
            ValueError: If target experiment not found or chain is broken.
        """
        query = """
        MATCH path = (target:Experiment {exp_id: $exp_id})-[:DERIVED_FROM*0..100]->(base:Experiment)
        WHERE NOT EXISTS((base)-[:DERIVED_FROM]->())
        WITH nodes(path) AS chain
        RETURN [n IN chain | {codebase: n.codebase}] AS chain
        ORDER BY size(chain) DESC
        LIMIT 1
        """
        result = await self._client.run_single(query, exp_id=target_exp_id)
        if not result:
            raise ValueError(f"Experiment {target_exp_id} not found or chain broken")

        # Chain comes target->...->base, we need base->...->target
        chain: list[dict[str, dict[str, str]]] = list(reversed(result["chain"]))
        return reconstruct_codebase(chain)

    # -- 2a. Preview rollback --

    async def preview_rollback(self, exp_id: str) -> RollbackPreview:
        """Preview what a rollback from exp_id would affect.

        Finds all descendants (via DERIVED_FROM and RETRY_OF) and returns
        rich summaries including checkpoint metrics and URIs.
        """
        query = """
        MATCH (target:Experiment {exp_id: $exp_id})
        OPTIONAL MATCH (desc:Experiment)-[:DERIVED_FROM|RETRY_OF*]->(target)
        WITH target, COLLECT(DISTINCT desc) AS descendants
        WITH [target] + descendants AS all_exps
        UNWIND all_exps AS e
        OPTIONAL MATCH (e)-[:PRODUCED]->(c:Checkpoint)
        WITH e, COLLECT(CASE WHEN c IS NOT NULL THEN {
            ckp_id: c.ckp_id, epoch: c.epoch, run: c.run,
            metrics_snapshot: c.metrics_snapshot, uri: c.uri,
            is_usable: c.is_usable
        } ELSE NULL END) AS raw_ckps
        WITH e, [x IN raw_ckps WHERE x IS NOT NULL] AS ckps
        RETURN e.exp_id AS exp_id, e.description AS description,
               e.status AS status, e.strategy AS strategy,
               e.usable AS usable, e.config_hash AS config_hash,
               e.created_at AS created_at, ckps AS checkpoints
        """
        records = await self._client.run_list(query, exp_id=exp_id)
        if not records:
            raise ValueError(f"Experiment {exp_id} not found")

        summaries = [_build_experiment_summary(r) for r in records]
        all_ckps = [c for s in summaries for c in s.checkpoints]

        # Count branches: experiments with >1 child among affected set
        branch_query = """
        MATCH (target:Experiment {exp_id: $exp_id})
        OPTIONAL MATCH (desc:Experiment)-[:DERIVED_FROM|RETRY_OF*]->(target)
        WITH [target] + COLLECT(DISTINCT desc) AS all_exps
        UNWIND all_exps AS e
        OPTIONAL MATCH (child:Experiment)-[:DERIVED_FROM|RETRY_OF]->(e)
        WHERE NOT child IN all_exps
        WITH COUNT(DISTINCT child) AS external_branches
        RETURN external_branches
        """
        branch_result = await self._client.run_single(branch_query, exp_id=exp_id)
        branch_count = branch_result["external_branches"] if branch_result else 0

        # Generate warning for checkpoints with saved weights
        saved_weight_count = sum(1 for c in all_ckps if c.uri)
        warning = None
        if saved_weight_count > 0:
            warning = f"{saved_weight_count} checkpoint(s) have saved weights at external URIs"

        return RollbackPreview(
            target_exp_id=exp_id,
            affected_experiments=summaries,
            branch_count=branch_count,
            total_experiments=len(summaries),
            total_checkpoints=len(all_ckps),
            warning=warning,
        )

    # -- 2b. Apply rollback --

    async def apply_rollback(
        self, preview: RollbackPreview, force: bool = False
    ) -> None:
        """Apply soft-delete (usable=false) to all nodes in the preview.

        Raises:
            ValueError: If branches exist and force is False.
        """
        if preview.branch_count > 0 and not force:
            raise ValueError(
                f"Rollback would orphan {preview.branch_count} branch(es). "
                "Use force=True to proceed."
            )

        exp_ids = [s.exp_id for s in preview.affected_experiments]
        ckp_ids = [c.ckp_id for s in preview.affected_experiments for c in s.checkpoints]

        if exp_ids:
            await self._client.run(
                """
                UNWIND $ids AS eid
                MATCH (e:Experiment {exp_id: eid})
                SET e.usable = false
                """,
                ids=exp_ids,
            )

        if ckp_ids:
            await self._client.run(
                """
                UNWIND $ids AS cid
                MATCH (c:Checkpoint {ckp_id: cid})
                SET c.is_usable = false
                """,
                ids=ckp_ids,
            )

    # -- 3. Squash chain --

    async def squash_chain(self, from_exp_id: str, to_exp_id: str) -> None:
        """Compact diffs between two experiments on a linear chain.

        Replaces intermediate experiments with a single cumulative diff.
        Intermediate nodes and their checkpoints are deleted from DB.

        Raises:
            ValueError: If chain is not linear or experiments not found.
        """
        # Get the chain between from and to
        chain_query = """
        MATCH path = (dest:Experiment {exp_id: $to_id})-[:DERIVED_FROM*]->(src:Experiment {exp_id: $from_id})
        RETURN [n IN nodes(path) | n.exp_id] AS chain_ids
        LIMIT 1
        """
        result = await self._client.run_single(
            chain_query, to_id=to_exp_id, from_id=from_exp_id
        )
        if not result:
            raise ValueError(
                f"No DERIVED_FROM chain found from {to_exp_id} to {from_exp_id}"
            )

        chain_ids: list[str] = result["chain_ids"]  # to -> ... -> from
        if len(chain_ids) < 3:
            raise ValueError("Nothing to squash: no intermediate nodes")

        # Verify linearity: each intermediate must have exactly 1 DERIVED_FROM child in chain
        intermediates = chain_ids[1:-1]  # exclude to and from
        for mid_id in intermediates:
            count_result = await self._client.run_single(
                """
                MATCH (child:Experiment)-[:DERIVED_FROM]->(e:Experiment {exp_id: $eid})
                RETURN COUNT(child) AS child_count
                """,
                eid=mid_id,
            )
            if count_result and count_result["child_count"] > 1:
                raise ValueError(
                    f"Chain is not linear: {mid_id} has branches"
                )

        # Reconstruct codebases at both endpoints
        from_codebase = await self.reconstruct_at(from_exp_id)
        to_codebase = await self.reconstruct_at(to_exp_id)

        # Compute cumulative diff
        from_snapshot = CodebaseSnapshot(files=from_codebase)
        to_snapshot = CodebaseSnapshot(files=to_codebase)
        cumulative_diff = compute_snapshot_diff(from_snapshot, to_snapshot)

        # Update to_exp codebase and re-point DERIVED_FROM
        await self._client.run(
            """
            MATCH (dest:Experiment {exp_id: $to_id})-[old:DERIVED_FROM]->()
            DELETE old
            WITH dest
            MATCH (src:Experiment {exp_id: $from_id})
            CREATE (dest)-[:DERIVED_FROM]->(src)
            SET dest.codebase = $new_codebase
            """,
            to_id=to_exp_id,
            from_id=from_exp_id,
            new_codebase=cumulative_diff,
        )

        # Delete intermediate nodes and their checkpoints
        for mid_id in intermediates:
            await self._client.run(
                """
                MATCH (e:Experiment {exp_id: $eid})
                OPTIONAL MATCH (e)-[:PRODUCED]->(c:Checkpoint)
                DETACH DELETE c
                DETACH DELETE e
                """,
                eid=mid_id,
            )

    # -- 4. Navigate backward --

    async def navigate_back(
        self, exp_id: str, steps: int = 1
    ) -> NavigationResult:
        """Navigate backwards in DERIVED_FROM chain by N steps.

        Raises:
            ValueError: If not enough ancestors exist.
        """
        if steps < 1:
            raise ValueError("steps must be >= 1")

        query = """
        MATCH path = (start:Experiment {exp_id: $exp_id})-[:DERIVED_FROM*""" + str(steps) + """..""" + str(steps) + """]->(ancestor:Experiment)
        WITH ancestor
        OPTIONAL MATCH (ancestor)-[:PRODUCED]->(c:Checkpoint)
        WITH ancestor, COLLECT(CASE WHEN c IS NOT NULL THEN {
            ckp_id: c.ckp_id, epoch: c.epoch, run: c.run,
            metrics_snapshot: c.metrics_snapshot, uri: c.uri,
            is_usable: c.is_usable
        } ELSE NULL END) AS raw_ckps
        WITH ancestor, [x IN raw_ckps WHERE x IS NOT NULL] AS ckps
        RETURN ancestor.exp_id AS exp_id, ancestor.description AS description,
               ancestor.status AS status, ancestor.strategy AS strategy,
               ancestor.usable AS usable, ancestor.config_hash AS config_hash,
               ancestor.created_at AS created_at, ckps AS checkpoints
        LIMIT 1
        """
        record = await self._client.run_single(query, exp_id=exp_id)
        if not record:
            raise ValueError(
                f"Cannot navigate {steps} step(s) back from {exp_id}"
            )

        summary = _build_experiment_summary(record)
        codebase = await self.reconstruct_at(summary.exp_id)

        return NavigationResult(
            exp_id=summary.exp_id,
            summary=summary,
            codebase=codebase,
        )

    # -- 5. Navigate forward --

    async def navigate_forward(
        self, exp_id: str, steps: int = 1
    ) -> NavigationResult:
        """Navigate forward in DERIVED_FROM chain by N steps.

        Raises:
            ValueError: If branch encountered or not enough descendants.
        """
        if steps < 1:
            raise ValueError("steps must be >= 1")

        current_id = exp_id
        for _ in range(steps):
            children = await self._client.run_list(
                """
                MATCH (child:Experiment)-[:DERIVED_FROM]->(e:Experiment {exp_id: $eid})
                RETURN child.exp_id AS exp_id
                """,
                eid=current_id,
            )
            if not children:
                raise ValueError(
                    f"Cannot navigate forward from {current_id}: no descendants"
                )
            if len(children) > 1:
                raise ValueError(
                    f"Branch at {current_id}: {len(children)} children. "
                    "Forward navigation requires linear chain."
                )
            current_id = children[0]["exp_id"]

        # Fetch rich summary at destination
        query = """
        MATCH (e:Experiment {exp_id: $eid})
        OPTIONAL MATCH (e)-[:PRODUCED]->(c:Checkpoint)
        WITH e, COLLECT(CASE WHEN c IS NOT NULL THEN {
            ckp_id: c.ckp_id, epoch: c.epoch, run: c.run,
            metrics_snapshot: c.metrics_snapshot, uri: c.uri,
            is_usable: c.is_usable
        } ELSE NULL END) AS raw_ckps
        WITH e, [x IN raw_ckps WHERE x IS NOT NULL] AS ckps
        RETURN e.exp_id AS exp_id, e.description AS description,
               e.status AS status, e.strategy AS strategy,
               e.usable AS usable, e.config_hash AS config_hash,
               e.created_at AS created_at, ckps AS checkpoints
        """
        record = await self._client.run_single(query, eid=current_id)
        if not record:
            raise ValueError(f"Experiment {current_id} not found")

        summary = _build_experiment_summary(record)
        codebase = await self.reconstruct_at(summary.exp_id)

        return NavigationResult(
            exp_id=summary.exp_id,
            summary=summary,
            codebase=codebase,
        )

    # -- 6. Visibility toggle --

    async def set_visibility(self, exp_id: str, usable: bool) -> list[str]:
        """Toggle experiment visibility with chain consistency.

        If restoring (usable=True), all ancestors back to base are also restored.
        If hiding (usable=False), only the target node is affected.

        Returns:
            List of affected exp_ids.
        """
        if usable:
            # Restore full ancestor chain
            query = """
            MATCH path = (target:Experiment {exp_id: $exp_id})-[:DERIVED_FROM*0..100]->(ancestor:Experiment)
            WITH COLLECT(DISTINCT ancestor.exp_id) AS all_ids
            UNWIND all_ids AS eid
            MATCH (e:Experiment {exp_id: eid})
            SET e.usable = true
            RETURN COLLECT(eid) AS affected
            """
            # The *0.. includes the target itself
            result = await self._client.run_single(query, exp_id=exp_id)
            return result["affected"] if result else []
        else:
            await self._client.run(
                """
                MATCH (e:Experiment {exp_id: $exp_id})
                SET e.usable = false
                """,
                exp_id=exp_id,
            )
            return [exp_id]
