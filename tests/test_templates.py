"""Tests for workflow templates."""

import pytest

from vmware_pilot.templates import (
    TEMPLATES,
    clone_and_test,
    compliance_scan,
    incident_response,
    plan_and_approve,
)


@pytest.mark.unit
class TestCloneAndTest:
    def test_creates_workflow(self):
        wf = clone_and_test(
            target_vm="db01",
            change_spec={"memory_mb": 32768},
            monitor_minutes=5,
            target="vcenter1",
        )
        assert wf.workflow_type == "clone_and_test"
        assert wf.state.value == "pending"
        assert len(wf.steps) == 6
        assert wf.params["target_vm"] == "db01"
        assert wf.params["staging_vm"] == "db01-staging"

    def test_step_actions(self):
        wf = clone_and_test(target_vm="web01", change_spec={"cpu": 4})
        actions = [s.action for s in wf.steps]
        assert actions == [
            "clone", "apply_changes", "monitor",
            "require_approval", "apply_to_production", "cleanup",
        ]

    def test_has_approval_gate(self):
        wf = clone_and_test(target_vm="app01", change_spec={})
        approval_steps = [s for s in wf.steps if s.action == "require_approval"]
        assert len(approval_steps) == 1


@pytest.mark.unit
class TestIncidentResponse:
    def test_creates_workflow(self):
        wf = incident_response(alert_entity="esxi-01", alert_name="HostMemoryUsage")
        assert wf.workflow_type == "incident_response"
        assert len(wf.steps) == 4
        assert wf.params["alert_entity"] == "esxi-01"

    def test_has_approval_gate(self):
        wf = incident_response(alert_entity="vm01", alert_name="CpuHigh")
        approval = [s for s in wf.steps if s.action == "require_approval"]
        assert len(approval) == 1


@pytest.mark.unit
class TestPlanAndApprove:
    def test_creates_workflow(self):
        ops = [
            {"action": "power_off", "vm_name": "db01"},
            {"action": "revert_snapshot", "vm_name": "db01", "snapshot_name": "baseline"},
            {"action": "power_on", "vm_name": "db01"},
        ]
        wf = plan_and_approve(operations=ops, target="vcenter1")
        assert wf.workflow_type == "plan_and_approve"
        assert wf.state.value == "pending"
        assert len(wf.steps) == 3
        assert wf.params["vm_names"] == ["db01"]

    def test_step_actions(self):
        ops = [{"action": "power_on", "vm_name": "web01"}]
        wf = plan_and_approve(operations=ops)
        actions = [s.action for s in wf.steps]
        assert actions == ["create_plan", "require_approval", "apply_plan"]

    def test_has_approval_gate(self):
        wf = plan_and_approve(operations=[{"action": "power_on", "vm_name": "x"}])
        approval = [s for s in wf.steps if s.action == "require_approval"]
        assert len(approval) == 1

    def test_rollback_on_apply_step(self):
        wf = plan_and_approve(operations=[{"action": "power_on", "vm_name": "x"}])
        apply_step = wf.steps[2]
        assert apply_step.rollback_tool == "vm_rollback_plan"

    def test_custom_description(self):
        wf = plan_and_approve(
            operations=[{"action": "power_on", "vm_name": "x"}],
            description="Restart db cluster",
        )
        assert "Restart db cluster" in wf.steps[1].params["message"]

    def test_multi_vm_names(self):
        ops = [
            {"action": "power_off", "vm_name": "db01"},
            {"action": "power_off", "vm_name": "db02"},
            {"action": "power_off", "vm_name": "db03"},
        ]
        wf = plan_and_approve(operations=ops)
        assert len(wf.params["vm_names"]) == 3


@pytest.mark.unit
class TestComplianceScan:
    def test_creates_workflow(self):
        wf = compliance_scan(target="vcenter1")
        assert wf.workflow_type == "compliance_scan"
        assert wf.state.value == "pending"
        assert len(wf.steps) == 3  # alarms + capacity + anomalies

    def test_no_approval_gate(self):
        wf = compliance_scan()
        approval = [s for s in wf.steps if s.action == "require_approval"]
        assert len(approval) == 0

    def test_skip_alarms(self):
        wf = compliance_scan(check_alarms=False)
        actions = [s.action for s in wf.steps]
        assert "check_alarms" not in actions
        assert "check_capacity" in actions

    def test_skip_capacity(self):
        wf = compliance_scan(check_capacity=False)
        actions = [s.action for s in wf.steps]
        assert "check_capacity" not in actions
        assert "check_alarms" in actions

    def test_uses_aria_and_monitor(self):
        wf = compliance_scan()
        skills = {s.skill for s in wf.steps}
        assert "monitor" in skills
        assert "aria" in skills


@pytest.mark.unit
class TestTemplateRegistry:
    def test_all_templates_registered(self):
        assert "clone_and_test" in TEMPLATES
        assert "incident_response" in TEMPLATES
        assert "plan_and_approve" in TEMPLATES
        assert "compliance_scan" in TEMPLATES

    def test_templates_callable(self):
        for name, fn in TEMPLATES.items():
            assert callable(fn)
