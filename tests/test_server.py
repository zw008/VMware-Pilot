"""Tests for MCP server tool behavior: approval-gate enforcement (#5) and
validate-before-persist / widened error handling (#8)."""

from pathlib import Path

import pytest

import mcp_server.server as server
from vmware_pilot.executor import WorkflowExecutor
from vmware_pilot.models import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    WorkflowStore,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = WorkflowStore(tmp_path / "wf.db")
    monkeypatch.setattr(server, "_store", s)
    monkeypatch.setattr(server, "_executor", WorkflowExecutor(s))
    return s


def _save(store: WorkflowStore, steps: list[WorkflowStep], wf_id: str) -> Workflow:
    wf = Workflow(
        id=wf_id, workflow_type="test", state=WorkflowState.PENDING,
        steps=steps, params={}, created_at="", updated_at="",
    )
    store.save(wf)
    return wf


def _step(i, tool, group_id="", action=None):
    return WorkflowStep(
        index=i, action=action or tool, skill="nsx", tool=tool,
        params={"id": "x"}, group_id=group_id,
    )


@pytest.mark.unit
class TestRunWorkflowGating:
    """Truth table for fix #5: (blocking findings, force) → refuse/run."""

    def test_ungated_destructive_without_force_refused(self, store):
        wf = _save(store, [_step(0, "delete_segment")], "wf-g1")
        result = server.run_workflow("wf-g1")
        assert "error" in result
        assert result["blocking_findings"][0]["kind"] == "ungated_destructive"
        # Nothing ran / nothing recorded as executed
        assert wf.steps[0].status == "pending"
        assert wf.state == WorkflowState.PENDING

    def test_ungated_destructive_with_force_runs_and_audits(self, store):
        wf = _save(store, [_step(0, "delete_segment")], "wf-g2")
        result = server.run_workflow("wf-g2", force=True)
        assert "error" not in result
        # Server has no dispatcher → honest dispatch_required, not completed
        assert result["outcome"] == "dispatch_required"
        assert any(e["action"] == "forced_run" for e in wf.audit_log)

    def test_destructive_in_parallel_group_refused(self, store):
        steps = [
            WorkflowStep(index=0, action="require_approval", skill="pilot",
                         tool="approve", params={}),
            _step(1, "delete_segment", group_id="g1"),
            _step(2, "delete_nat_rule", group_id="g1"),
        ]
        _save(store, steps, "wf-g3")
        result = server.run_workflow("wf-g3")
        assert "error" in result
        kinds = {f["kind"] for f in result["blocking_findings"]}
        assert "destructive_in_parallel_group" in kinds

    def test_gated_workflow_runs_without_force(self, store):
        steps = [
            WorkflowStep(index=0, action="require_approval", skill="pilot",
                         tool="approve", params={}),
            _step(1, "delete_segment"),
        ]
        _save(store, steps, "wf-g4")
        result = server.run_workflow("wf-g4")
        assert "error" not in result
        assert result["state"] == "awaiting_approval"

    def test_clean_workflow_runs_without_force(self, store):
        _save(store, [_step(0, "list_segments")], "wf-g5")
        result = server.run_workflow("wf-g5")
        assert "error" not in result
        assert result["outcome"] == "dispatch_required"

    def test_clean_workflow_with_force_no_forced_audit(self, store):
        wf = _save(store, [_step(0, "list_segments")], "wf-g6")
        result = server.run_workflow("wf-g6", force=True)
        assert "error" not in result
        assert not any(e["action"] == "forced_run" for e in wf.audit_log)


@pytest.mark.unit
class TestRunWorkflowHonesty:
    """Fix #1 at the MCP layer: noop dispatch must never report completed."""

    def test_run_workflow_never_fakes_completion(self, store):
        _save(store, [_step(0, "list_segments"), _step(1, "get_alarms")], "wf-h1")
        result = server.run_workflow("wf-h1")
        assert result["state"] != "completed"
        assert result["outcome"] == "dispatch_required"
        assert len(result["pending_dispatch"]) == 2
        assert all(s["status"] == "not_executed" for s in result["steps"])


@pytest.mark.unit
class TestCreateWorkflowValidation:
    """Fix #8: invalid template name must not persist a workflow."""

    @pytest.mark.parametrize("bad_name", ["", "../evil", "a/b", ".hidden", "a\\b"])
    def test_invalid_name_with_template_not_persisted(self, store, bad_name):
        result = server.create_workflow(
            name=bad_name, description="d",
            steps=[{"action": "a", "skill": "monitor", "tool": "get_alarms", "params": {}}],
            save_as_template=True,
        )
        assert "error" in result
        assert store.list_all() == []

    def test_valid_name_without_template_persists(self, store):
        result = server.create_workflow(
            name="ok_flow", description="d",
            steps=[{"action": "a", "skill": "monitor", "tool": "get_alarms", "params": {}}],
            save_as_template=False,
        )
        assert "error" not in result
        assert store.load(result["workflow_id"]) is not None


@pytest.mark.unit
class TestConfirmDraftValidation:
    """Fix #8: confirm_draft validates the name before flipping state."""

    def test_bad_template_name_keeps_draft_state(self, store):
        wf = Workflow(
            id="wf-d1", workflow_type="bad/name", state=WorkflowState.DRAFT,
            steps=[_step(0, "list_segments")],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)
        result = server.confirm_draft("wf-d1", save_as_template=True)
        assert "error" in result
        assert wf.state == WorkflowState.DRAFT
