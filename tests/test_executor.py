"""Tests for the workflow executor."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from vmware_pilot.executor import WorkflowExecutor
from vmware_pilot.models import Workflow, WorkflowState, WorkflowStep, WorkflowStore


def _make_store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(tmp_path / "test.db")


def _success_dispatch(skill: str, tool: str, params: dict[str, Any]) -> dict:
    return {"ok": True, "skill": skill, "tool": tool}


def _fail_dispatch(skill: str, tool: str, params: dict[str, Any]) -> dict:
    if tool == "failing_tool":
        raise RuntimeError("simulated failure")
    return {"ok": True}


@pytest.mark.unit
class TestExecutor:
    def test_run_simple_workflow(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store, dispatch=_success_dispatch)

        wf = Workflow(
            id="wf-1", workflow_type="test", state=WorkflowState.PENDING,
            steps=[
                WorkflowStep(index=0, action="step1", skill="aiops", tool="vm_power_on", params={"vm": "a"}),
                WorkflowStep(index=1, action="step2", skill="aiops", tool="vm_power_off", params={"vm": "a"}),
            ],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)
        result = executor.run_until_checkpoint(wf)
        assert result["state"] == "completed"
        assert all(s["status"] == "success" for s in result["steps"])

    def test_approval_gate_pauses(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store, dispatch=_success_dispatch)

        wf = Workflow(
            id="wf-2", workflow_type="test", state=WorkflowState.PENDING,
            steps=[
                WorkflowStep(index=0, action="clone", skill="aiops", tool="deploy_linked_clone", params={}),
                WorkflowStep(index=1, action="require_approval", skill="pilot", tool="approve", params={"message": "ok?"}),
                WorkflowStep(index=2, action="commit", skill="aiops", tool="vm_power_on", params={}),
            ],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)

        # Run — should pause at approval
        result = executor.run_until_checkpoint(wf)
        assert result["state"] == "awaiting_approval"
        assert wf.steps[0].status == "success"
        assert wf.steps[1].status == "pending"  # approval not yet done
        assert wf.steps[2].status == "pending"

    def test_resume_after_approval(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store, dispatch=_success_dispatch)

        wf = Workflow(
            id="wf-3", workflow_type="test", state=WorkflowState.PENDING,
            steps=[
                WorkflowStep(index=0, action="clone", skill="aiops", tool="deploy_linked_clone", params={}),
                WorkflowStep(index=1, action="require_approval", skill="pilot", tool="approve", params={}),
                WorkflowStep(index=2, action="commit", skill="aiops", tool="vm_power_on", params={}),
            ],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)

        executor.run_until_checkpoint(wf)
        assert wf.state == WorkflowState.AWAITING_APPROVAL

        result = executor.resume_after_approval(wf, approver="wei")
        assert result["state"] == "completed"
        assert result["approved_by"] == "wei"

    def test_failure_skips_remaining(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store, dispatch=_fail_dispatch)

        wf = Workflow(
            id="wf-4", workflow_type="test", state=WorkflowState.PENDING,
            steps=[
                WorkflowStep(index=0, action="ok", skill="aiops", tool="vm_power_on", params={}),
                WorkflowStep(index=1, action="fail", skill="aiops", tool="failing_tool", params={}),
                WorkflowStep(index=2, action="skip", skill="aiops", tool="vm_power_off", params={}),
            ],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)

        result = executor.run_until_checkpoint(wf)
        assert result["state"] == "failed"
        assert result["steps"][0]["status"] == "success"
        assert result["steps"][1]["status"] == "failed"
        assert result["steps"][2]["status"] == "skipped"

    def test_rollback(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store, dispatch=_success_dispatch)

        wf = Workflow(
            id="wf-5", workflow_type="test", state=WorkflowState.RUNNING,
            steps=[
                WorkflowStep(
                    index=0, action="clone", skill="aiops", tool="deploy_linked_clone", params={},
                    status="success", rollback_tool="vm_power_off", rollback_params={"vm": "staging"},
                ),
                WorkflowStep(
                    index=1, action="apply", skill="aiops", tool="vm_reconfigure", params={},
                    status="failed",
                ),
            ],
            params={}, created_at="", updated_at="",
        )
        store.save(wf)

        result = executor.rollback(wf)
        assert result["state"] == "failed"
        assert len(result["rollback_results"]) == 1
        assert result["rollback_results"][0]["status"] == "success"

    def test_blocked_by_policy(self, tmp_path):
        store = _make_store(tmp_path)
        executor = WorkflowExecutor(store)

        wf = Workflow(
            id="wf-6", workflow_type="test", state=WorkflowState.RUNNING,
            steps=[], params={}, created_at="", updated_at="",
        )
        store.save(wf)

        result = executor.mark_blocked(wf, "Production changes require maintenance window")
        assert result["state"] == "blocked_by_policy"
        assert result["blocked_reason"] == "Production changes require maintenance window"
