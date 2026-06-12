"""Monitoring & incident workflow templates — incident response, causal-chain
alert investigation, and read-only compliance scan."""

from __future__ import annotations

from vmware_pilot.templates._common import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    datetime,
    new_workflow_id,
    parallel_group,
    timezone,
)


def incident_response(
    alert_entity: str,
    alert_name: str,
    target: str = "",
) -> Workflow:
    """Auto-diagnose and remediate an alert.

    Steps:
      1. Get alarm details
      2. Collect diagnostics (events, VM info)
      3. Await approval for remediation
      4. Execute remediation (acknowledge alarm)
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    steps = [
        WorkflowStep(
            index=0,
            action="get_alarms",
            skill="monitor",
            tool="get_alarms",
            params={"target": target},
        ),
        WorkflowStep(
            index=1,
            action="get_events",
            skill="monitor",
            tool="get_events",
            params={"hours": 1, "severity": "critical", "target": target},
        ),
        WorkflowStep(
            index=2,
            action="require_approval",
            skill="pilot",
            tool="approve",
            params={"message": f"Alert '{alert_name}' on '{alert_entity}'. Acknowledge and clear?"},
        ),
        WorkflowStep(
            index=3,
            action="acknowledge",
            skill="aiops",
            tool="acknowledge_vcenter_alarm",
            params={"entity_name": alert_entity, "alarm_name": alert_name, "target": target},
        ),
    ]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="incident_response",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "alert_entity": alert_entity,
            "alert_name": alert_name,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )


def compliance_scan(
    target: str = "",
    check_alarms: bool = True,
    check_capacity: bool = True,
) -> Workflow:
    """Periodic compliance scan — collect health data, report, and flag issues.

    Steps:
      1. Check active alarms (monitor)
      2. Check capacity remaining (aria)
      3. Collect anomalies (aria)
      4. Generate compliance report summary

    All steps are read-only — no approval gate needed.

    Args:
        target: vCenter/Aria target name.
        check_alarms: Include alarm check (default True).
        check_capacity: Include capacity check (default True).
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = []
    idx = 0

    if check_alarms:
        steps.append(WorkflowStep(
            index=idx, action="check_alarms", skill="monitor",
            tool="get_alarms", params={"target": target},
        ))
        idx += 1

    if check_capacity:
        steps.append(WorkflowStep(
            index=idx, action="check_capacity", skill="aria",
            tool="get_capacity_overview", params={"target": target},
        ))
        idx += 1

    steps.append(WorkflowStep(
        index=idx, action="check_anomalies", skill="aria",
        tool="list_anomalies", params={"target": target},
    ))

    return Workflow(
        id=new_workflow_id(),
        workflow_type="compliance_scan",
        state=WorkflowState.PENDING,
        steps=steps,
        params={"target": target, "check_alarms": check_alarms, "check_capacity": check_capacity},
        created_at=now,
        updated_at=now,
    )


def investigate_alert(
    alert_entity: str,
    alert_name: str = "",
    deep_dive: bool = False,
    target: str = "",
) -> Workflow:
    """Causal-chain root-cause investigation per investigation-protocol.md.

    Encodes the four-criteria root cause completeness loop from the Enterprise
    Harness Engineering framework as a pilot workflow.

    Stage 1 — parallel-group "round1-gather":
        Fetch alarms, events, and Aria alerts/metrics for the affected entity
        concurrently. All three are L1/L2 read-only and independent.
    Stage 2 — synthesis checkpoint:
        Pause for the AI agent to apply the four criteria
        (falsifiability / sufficiency / necessity / mechanism) and decide
        whether the root cause is complete.
    Stage 3 (only when ``deep_dive=True``) — parallel-group "round2-gather":
        Broader evidence: anomalies, capacity context, recent alerts in the
        same cluster. Used when round 1 fails the necessity or mechanism check.
    Stage 4 (only when ``deep_dive=True``) — final synthesis checkpoint.

    The agent is responsible for producing the structured report (root cause
    plus four-criteria evidence). Pilot only orchestrates the data gathering
    and the human-approval gates.

    Args:
        alert_entity: Resource that triggered the alert (VM name, host, cluster).
        alert_name: Optional human-readable alert label, surfaced in approval prompts.
        deep_dive: If True, append a second round of broader gathering and a
            second synthesis checkpoint (max three rounds total — a third would
            require a follow-up workflow).
        target: vCenter / Aria target identifier; defaults to the first
            configured target on each skill.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    label = alert_name or alert_entity

    round1 = [
        WorkflowStep(
            index=0, action="gather_alarms",
            skill="monitor", tool="list_alarms",
            params={"entity_name": alert_entity, "target": target},
        ),
        WorkflowStep(
            index=1, action="gather_events",
            skill="monitor", tool="list_events",
            params={"hours": 2, "entity_name": alert_entity, "target": target},
        ),
        WorkflowStep(
            index=2, action="gather_aria_alerts",
            skill="aria", tool="list_alerts",
            params={"resource_name": alert_entity, "target": target},
        ),
    ]
    parallel_group("round1-gather", round1)

    checkpoint1 = WorkflowStep(
        index=3, action="require_approval",
        skill="pilot", tool="approve",
        params={
            "message": (
                f"Round 1 evidence gathered for '{label}'. "
                "Apply the four-criteria check from references/investigation-protocol.md: "
                "(1) falsifiability, (2) sufficiency, (3) necessity, (4) mechanism. "
                "APPROVE if root cause is complete and you are ready to write the report. "
                "REJECT to escalate or relaunch with deep_dive=True."
            ),
        },
    )

    steps = round1 + [checkpoint1]

    if deep_dive:
        round2 = [
            WorkflowStep(
                index=4, action="gather_anomalies",
                skill="aria", tool="list_anomalies",
                params={"resource_name": alert_entity, "target": target},
            ),
            WorkflowStep(
                index=5, action="gather_capacity",
                skill="aria", tool="capacity_overview",
                params={"resource_name": alert_entity, "target": target},
            ),
            WorkflowStep(
                index=6, action="gather_recent_alerts",
                skill="aria", tool="list_alerts",
                params={"hours": 24, "target": target},
            ),
        ]
        parallel_group("round2-gather", round2)

        checkpoint2 = WorkflowStep(
            index=7, action="require_approval",
            skill="pilot", tool="approve",
            params={
                "message": (
                    f"Round 2 evidence gathered for '{label}'. "
                    "Re-apply the four-criteria check. "
                    "APPROVE if root cause is now complete. "
                    "REJECT and escalate if a third round is needed — "
                    "the protocol caps at three rounds before human handoff."
                ),
            },
        )

        steps += round2 + [checkpoint2]

    return Workflow(
        id=new_workflow_id(),
        workflow_type="investigate_alert",
        state=WorkflowState.PENDING,
        steps=steps,
        params={
            "alert_entity": alert_entity,
            "alert_name": alert_name,
            "deep_dive": deep_dive,
            "target": target,
        },
        created_at=now,
        updated_at=now,
    )
