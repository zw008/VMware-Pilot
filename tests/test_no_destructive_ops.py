"""Safety boundary tests -- verify destructive workflow templates have approval gates.

VMware-Pilot orchestrates multi-step workflows. Destructive templates (those
that include power_off, delete, revert, or other state-changing tool calls)
MUST contain a ``require_approval`` step before any destructive action.

Uses Python AST parsing to verify the safety gate exists in each template
function's generated workflow steps.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

TEMPLATES_FILE = (
    Path(__file__).resolve().parent.parent / "vmware_pilot" / "templates.py"
)

# Template functions that generate workflows with destructive operations.
# Each MUST include a WorkflowStep with action="require_approval".
DESTRUCTIVE_TEMPLATES: list[str] = [
    "clone_and_test",
    "incident_response",
    "plan_and_approve",
    "network_segment_setup",
    "vks_cluster_deploy",
    "rolling_restart",
    "capacity_expansion",
    "disaster_recovery",
    "patch_deployment",
    "storage_expansion",
    "baseline_remediate",
]


def _has_require_approval(file_path: Path, func_name: str) -> bool:
    """Return True if *func_name* contains a ``require_approval`` string literal."""
    tree = ast.parse(file_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            source = ast.dump(node)
            return "require_approval" in source
    return False


@pytest.mark.unit
class TestDestructiveTemplateSafety:
    """Every destructive workflow template must contain a require_approval gate."""

    @pytest.mark.parametrize("func_name", DESTRUCTIVE_TEMPLATES)
    def test_has_approval_gate(self, func_name: str) -> None:
        assert TEMPLATES_FILE.exists(), f"{TEMPLATES_FILE} not found"
        assert _has_require_approval(TEMPLATES_FILE, func_name), (
            f"Template '{func_name}' in templates.py lacks a require_approval "
            f"approval gate before destructive operations"
        )
