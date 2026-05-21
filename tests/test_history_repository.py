"""Tests for ExperimentRepository history management operations."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from graph_lineage.history.models import (
    CheckpointSummary,
    ExperimentSummary,
    NavigationResult,
    RollbackPreview,
)
from graph_lineage.history.repository import ExperimentRepository, _build_experiment_summary


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """AsyncNeo4jClient mock with configurable responses."""
    client = AsyncMock()
    client.run = AsyncMock()
    client.run_single = AsyncMock(return_value=None)
    client.run_list = AsyncMock(return_value=[])
    return client


@pytest.fixture
def repo(mock_client):
    return ExperimentRepository(mock_client)


# ── Helper data ────────────────────────────────────────────────────────

BASE_CODEBASE = {"config.yaml": "lr: 1e-4\n", "train.py": "print('v1')\n"}
DIFF_V2 = {"config.yaml": "--- a/config.yaml\n+++ b/config.yaml\n@@ -1 +1 @@\n-lr: 1e-4\n+lr: 2e-4\n"}

EXP_RECORD_BASE = {
    "exp_id": "e-001",
    "description": "Base experiment",
    "status": "COMPLETED",
    "strategy": "NEW",
    "usable": True,
    "config_hash": "abc123",
    "created_at": "2026-01-01",
    "checkpoints": [
        {"ckp_id": "c-001", "epoch": 1, "run": 0, "metrics_snapshot": {"loss": 0.5}, "uri": "s3://bucket/c-001", "is_usable": True},
    ],
}

EXP_RECORD_DERIVED = {
    "exp_id": "e-002",
    "description": "LR tuned",
    "status": "COMPLETED",
    "strategy": "BRANCH",
    "usable": True,
    "config_hash": "def456",
    "created_at": "2026-01-02",
    "checkpoints": [
        {"ckp_id": "c-002", "epoch": 2, "run": 0, "metrics_snapshot": {"loss": 0.3}, "uri": "s3://bucket/c-002", "is_usable": True},
    ],
}


# ── _build_experiment_summary ──────────────────────────────────────────


class TestBuildSummary:
    def test_builds_from_record(self):
        summary = _build_experiment_summary(EXP_RECORD_BASE)
        assert summary.exp_id == "e-001"
        assert summary.checkpoint_count == 1
        assert summary.checkpoints[0].ckp_id == "c-001"
        assert summary.checkpoints[0].metrics_snapshot == {"loss": 0.5}

    def test_empty_checkpoints(self):
        record = {**EXP_RECORD_BASE, "checkpoints": []}
        summary = _build_experiment_summary(record)
        assert summary.checkpoint_count == 0
        assert summary.checkpoints == []

    def test_missing_optional_fields(self):
        record = {"exp_id": "e-min", "checkpoints": []}
        summary = _build_experiment_summary(record)
        assert summary.description == ""
        assert summary.created_at is None


# ── reconstruct_at ─────────────────────────────────────────────────────


class TestReconstructAt:
    @pytest.mark.asyncio
    async def test_base_experiment(self, repo, mock_client):
        mock_client.run_single.return_value = {
            "chain": [{"codebase": BASE_CODEBASE}]
        }
        result = await repo.reconstruct_at("e-001")
        assert result == BASE_CODEBASE

    @pytest.mark.asyncio
    async def test_derived_experiment(self, repo, mock_client):
        # Chain: target(e-002) → base(e-001), reversed to base→target
        mock_client.run_single.return_value = {
            "chain": [
                {"codebase": DIFF_V2},   # e-002 (target, first in chain)
                {"codebase": BASE_CODEBASE},  # e-001 (base, last in chain)
            ]
        }
        result = await repo.reconstruct_at("e-002")
        assert "lr: 2e-4" in result["config.yaml"]

    @pytest.mark.asyncio
    async def test_not_found_raises(self, repo, mock_client):
        mock_client.run_single.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await repo.reconstruct_at("e-999")


# ── preview_rollback ───────────────────────────────────────────────────


class TestPreviewRollback:
    @pytest.mark.asyncio
    async def test_preview_with_descendants(self, repo, mock_client):
        mock_client.run_list.return_value = [EXP_RECORD_BASE, EXP_RECORD_DERIVED]
        mock_client.run_single.return_value = {"external_branches": 0}

        preview = await repo.preview_rollback("e-001")
        assert preview.total_experiments == 2
        assert preview.total_checkpoints == 2
        assert preview.branch_count == 0
        assert preview.warning is not None  # has saved weights

    @pytest.mark.asyncio
    async def test_preview_no_weights_no_warning(self, repo, mock_client):
        record = {**EXP_RECORD_BASE, "checkpoints": [
            {"ckp_id": "c-x", "epoch": 0, "run": 0, "metrics_snapshot": {}, "uri": None, "is_usable": True}
        ]}
        mock_client.run_list.return_value = [record]
        mock_client.run_single.return_value = {"external_branches": 0}

        preview = await repo.preview_rollback("e-001")
        assert preview.warning is None

    @pytest.mark.asyncio
    async def test_preview_not_found(self, repo, mock_client):
        mock_client.run_list.return_value = []
        with pytest.raises(ValueError, match="not found"):
            await repo.preview_rollback("e-999")


# ── apply_rollback ─────────────────────────────────────────────────────


class TestApplyRollback:
    @pytest.mark.asyncio
    async def test_apply_sets_usable_false(self, repo, mock_client):
        preview = RollbackPreview(
            target_exp_id="e-001",
            affected_experiments=[
                ExperimentSummary(exp_id="e-001", checkpoints=[
                    CheckpointSummary(ckp_id="c-001", epoch=1, run=0)
                ]),
            ],
            branch_count=0,
            total_experiments=1,
            total_checkpoints=1,
        )
        await repo.apply_rollback(preview)
        # Two calls: one for experiments, one for checkpoints
        assert mock_client.run.await_count == 2

    @pytest.mark.asyncio
    async def test_apply_refuses_branches_without_force(self, repo):
        preview = RollbackPreview(
            target_exp_id="e-001",
            affected_experiments=[],
            branch_count=2,
            total_experiments=1,
            total_checkpoints=0,
        )
        with pytest.raises(ValueError, match="orphan"):
            await repo.apply_rollback(preview)

    @pytest.mark.asyncio
    async def test_apply_with_force(self, repo, mock_client):
        preview = RollbackPreview(
            target_exp_id="e-001",
            affected_experiments=[
                ExperimentSummary(exp_id="e-001", checkpoints=[]),
            ],
            branch_count=2,
            total_experiments=1,
            total_checkpoints=0,
        )
        await repo.apply_rollback(preview, force=True)
        assert mock_client.run.await_count >= 1


# ── squash_chain ───────────────────────────────────────────────────────


class TestSquashChain:
    @pytest.mark.asyncio
    async def test_squash_refuses_no_intermediates(self, repo, mock_client):
        mock_client.run_single.return_value = {"chain_ids": ["e-002", "e-001"]}
        with pytest.raises(ValueError, match="Nothing to squash"):
            await repo.squash_chain("e-001", "e-002")

    @pytest.mark.asyncio
    async def test_squash_refuses_nonlinear(self, repo, mock_client):
        # First call: chain query
        # Second call: linearity check returns >1 child
        mock_client.run_single.side_effect = [
            {"chain_ids": ["e-003", "e-002", "e-001"]},
            {"child_count": 2},  # e-002 has branches
        ]
        with pytest.raises(ValueError, match="not linear"):
            await repo.squash_chain("e-001", "e-003")

    @pytest.mark.asyncio
    async def test_squash_not_found(self, repo, mock_client):
        mock_client.run_single.return_value = None
        with pytest.raises(ValueError, match="No DERIVED_FROM chain"):
            await repo.squash_chain("e-001", "e-999")


# ── navigate_back ──────────────────────────────────────────────────────


class TestNavigateBack:
    @pytest.mark.asyncio
    async def test_back_one_step(self, repo, mock_client):
        mock_client.run_single.side_effect = [
            EXP_RECORD_BASE,  # navigate query
            {"chain": [{"codebase": BASE_CODEBASE}]},  # reconstruct_at
        ]
        result = await repo.navigate_back("e-002", steps=1)
        assert result.exp_id == "e-001"
        assert result.summary.status == "COMPLETED"
        assert isinstance(result.codebase, dict)

    @pytest.mark.asyncio
    async def test_back_invalid_steps(self, repo):
        with pytest.raises(ValueError, match="steps must be >= 1"):
            await repo.navigate_back("e-001", steps=0)

    @pytest.mark.asyncio
    async def test_back_no_ancestor(self, repo, mock_client):
        mock_client.run_single.return_value = None
        with pytest.raises(ValueError, match="Cannot navigate"):
            await repo.navigate_back("e-001", steps=5)


# ── navigate_forward ───────────────────────────────────────────────────


class TestNavigateForward:
    @pytest.mark.asyncio
    async def test_forward_one_step(self, repo, mock_client):
        mock_client.run_list.return_value = [{"exp_id": "e-002"}]
        mock_client.run_single.side_effect = [
            EXP_RECORD_DERIVED,  # summary query
            {"chain": [  # reconstruct chain
                {"codebase": DIFF_V2},
                {"codebase": BASE_CODEBASE},
            ]},
        ]
        result = await repo.navigate_forward("e-001", steps=1)
        assert result.exp_id == "e-002"

    @pytest.mark.asyncio
    async def test_forward_branch_raises(self, repo, mock_client):
        mock_client.run_list.return_value = [
            {"exp_id": "e-002"},
            {"exp_id": "e-003"},
        ]
        with pytest.raises(ValueError, match="Branch"):
            await repo.navigate_forward("e-001", steps=1)

    @pytest.mark.asyncio
    async def test_forward_no_children(self, repo, mock_client):
        mock_client.run_list.return_value = []
        with pytest.raises(ValueError, match="no descendants"):
            await repo.navigate_forward("e-001", steps=1)

    @pytest.mark.asyncio
    async def test_forward_invalid_steps(self, repo):
        with pytest.raises(ValueError, match="steps must be >= 1"):
            await repo.navigate_forward("e-001", steps=0)


# ── set_visibility ─────────────────────────────────────────────────────


class TestSetVisibility:
    @pytest.mark.asyncio
    async def test_hide_single_node(self, repo, mock_client):
        result = await repo.set_visibility("e-002", usable=False)
        assert result == ["e-002"]
        mock_client.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_propagates_to_ancestors(self, repo, mock_client):
        mock_client.run_single.return_value = {"affected": ["e-002", "e-001"]}
        result = await repo.set_visibility("e-002", usable=True)
        assert "e-001" in result
        assert "e-002" in result


# ── Pydantic models ───────────────────────────────────────────────────


class TestModels:
    def test_rollback_preview_defaults(self):
        p = RollbackPreview(target_exp_id="e-001")
        assert p.affected_experiments == []
        assert p.warning is None

    def test_navigation_result(self):
        s = ExperimentSummary(exp_id="e-001")
        n = NavigationResult(exp_id="e-001", summary=s)
        assert n.codebase == {}

    def test_checkpoint_summary(self):
        c = CheckpointSummary(ckp_id="c-001", epoch=1, run=0)
        assert c.is_usable is True
        assert c.uri is None
