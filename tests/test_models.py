"""Tests for workflow models and persistence."""

import pytest

from vmware_pilot.models import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    WorkflowStore,
    new_workflow_id,
)


@pytest.mark.unit
class TestWorkflow:
    def test_new_id_format(self):
        wid = new_workflow_id()
        assert wid.startswith("wf-")
        assert len(wid) > 15

    def test_workflow_log(self):
        wf = Workflow(
            id="wf-test", workflow_type="test", state=WorkflowState.PENDING,
            steps=[], params={}, created_at="", updated_at="",
        )
        wf.log("started", "test detail")
        assert len(wf.audit_log) == 1
        assert wf.audit_log[0]["action"] == "started"

    def test_current_step(self):
        steps = [
            WorkflowStep(index=0, action="a", skill="s", tool="t", params={}, status="success"),
            WorkflowStep(index=1, action="b", skill="s", tool="t", params={}, status="pending"),
        ]
        wf = Workflow(
            id="wf-test", workflow_type="test", state=WorkflowState.RUNNING,
            steps=steps, params={}, created_at="", updated_at="",
        )
        assert wf.current_step().index == 1

    def test_to_dict(self):
        wf = Workflow(
            id="wf-test", workflow_type="test", state=WorkflowState.PENDING,
            steps=[], params={"a": 1}, created_at="t1", updated_at="t2",
        )
        d = wf.to_dict()
        assert d["state"] == "pending"
        assert d["params"]["a"] == 1


@pytest.mark.unit
class TestWorkflowStore:
    def setup_method(self, tmp_path=None):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.store = WorkflowStore(self._tmp.name)

    def teardown_method(self):
        import os
        os.unlink(self._tmp.name)

    def test_save_and_load(self):
        wf = Workflow(
            id="wf-001", workflow_type="clone_and_test", state=WorkflowState.PENDING,
            steps=[WorkflowStep(index=0, action="clone", skill="aiops", tool="deploy_linked_clone", params={"vm": "db01"})],
            params={"target_vm": "db01"}, created_at="2026-01-01", updated_at="2026-01-01",
        )
        self.store.save(wf)
        loaded = self.store.load("wf-001")
        assert loaded is not None
        assert loaded.id == "wf-001"
        assert loaded.workflow_type == "clone_and_test"
        assert loaded.state == WorkflowState.PENDING
        assert len(loaded.steps) == 1

    def test_load_nonexistent(self):
        assert self.store.load("wf-nope") is None

    def test_list_active(self):
        for i, state in enumerate([WorkflowState.PENDING, WorkflowState.RUNNING, WorkflowState.COMPLETED]):
            wf = Workflow(
                id=f"wf-{i}", workflow_type="test", state=state,
                steps=[], params={}, created_at=f"2026-01-0{i+1}", updated_at=f"2026-01-0{i+1}",
            )
            self.store.save(wf)
        active = self.store.list_active()
        assert len(active) == 2  # completed is excluded

    def test_delete(self):
        wf = Workflow(
            id="wf-del", workflow_type="test", state=WorkflowState.PENDING,
            steps=[], params={}, created_at="", updated_at="",
        )
        self.store.save(wf)
        self.store.delete("wf-del")
        assert self.store.load("wf-del") is None


@pytest.mark.unit
class TestSecretCacheLifecycle:
    """Fix #3: live cache keeps real secrets in-process; DB stays redacted."""

    def _wf_with_secret(self):
        return Workflow(
            id="wf-sec", workflow_type="test", state=WorkflowState.PENDING,
            steps=[WorkflowStep(index=0, action="a", skill="aiops", tool="vm_guest_exec",
                                params={"vm": "db01", "password": "s3cr3t!"})],
            params={"token": "tok-abc"}, created_at="", updated_at="",
        )

    def test_save_then_load_same_process_keeps_real_secrets(self, tmp_path):
        store = WorkflowStore(tmp_path / "wf.db")
        wf = self._wf_with_secret()
        store.save(wf)
        loaded = store.load("wf-sec")
        # Cache hit: the LIVE object, secrets intact for dispatch.
        assert loaded is wf
        assert loaded.steps[0].params["password"] == "s3cr3t!"
        assert loaded.params["token"] == "tok-abc"

    def test_db_row_is_redacted(self, tmp_path):
        import json
        import sqlite3
        store = WorkflowStore(tmp_path / "wf.db")
        store.save(self._wf_with_secret())
        conn = sqlite3.connect(str(tmp_path / "wf.db"))
        raw = conn.execute("SELECT data FROM workflows WHERE id='wf-sec'").fetchone()[0]
        conn.close()
        assert "s3cr3t!" not in raw
        assert "tok-abc" not in raw
        data = json.loads(raw)
        assert data["steps"][0]["params"]["password"] == "***"
        assert data["params"]["token"] == "***"

    def test_secrets_do_not_survive_process_restart(self, tmp_path):
        store = WorkflowStore(tmp_path / "wf.db")
        store.save(self._wf_with_secret())
        # Fresh store == new process: cache miss → redacted DB copy.
        fresh = WorkflowStore(tmp_path / "wf.db")
        loaded = fresh.load("wf-sec")
        assert loaded.steps[0].params["password"] == "***"

    def test_delete_evicts_cache(self, tmp_path):
        store = WorkflowStore(tmp_path / "wf.db")
        store.save(self._wf_with_secret())
        store.delete("wf-sec")
        assert store.load("wf-sec") is None
