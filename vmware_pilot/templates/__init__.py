"""Built-in workflow templates — predefined multi-step operations.

Each template function returns a Workflow with pre-configured steps.
The executor runs them; the AI agent only calls plan/run/approve/rollback.

The templates are organized by domain into sibling modules (vm, network, k8s,
storage, monitoring, baseline); this package re-exports them so the public API
(``from vmware_pilot.templates import get_all_templates, clone_and_test, …``)
and the built-in template names/IDs are unchanged.
"""

from __future__ import annotations

from typing import Any

from vmware_pilot.templates._common import parallel_group
from vmware_pilot.templates.baseline import (
    baseline_audit,
    baseline_capture,
    baseline_remediate,
)
from vmware_pilot.templates.k8s import vks_cluster_deploy
from vmware_pilot.templates.monitoring import (
    compliance_scan,
    incident_response,
    investigate_alert,
)
from vmware_pilot.templates.network import network_segment_setup
from vmware_pilot.templates.storage import storage_expansion
from vmware_pilot.templates.vm import (
    capacity_expansion,
    clone_and_test,
    disaster_recovery,
    patch_deployment,
    plan_and_approve,
    rolling_restart,
)

__all__ = [
    "BUILTIN_TEMPLATES",
    "TEMPLATES",
    "baseline_audit",
    "baseline_capture",
    "baseline_remediate",
    "capacity_expansion",
    "clone_and_test",
    "compliance_scan",
    "disaster_recovery",
    "get_all_templates",
    "incident_response",
    "investigate_alert",
    "network_segment_setup",
    "parallel_group",
    "patch_deployment",
    "plan_and_approve",
    "rolling_restart",
    "storage_expansion",
    "vks_cluster_deploy",
]


BUILTIN_TEMPLATES = {
    "clone_and_test": clone_and_test,
    "incident_response": incident_response,
    "investigate_alert": investigate_alert,
    "plan_and_approve": plan_and_approve,
    "compliance_scan": compliance_scan,
    "network_segment_setup": network_segment_setup,
    "vks_cluster_deploy": vks_cluster_deploy,
    "rolling_restart": rolling_restart,
    "capacity_expansion": capacity_expansion,
    "disaster_recovery": disaster_recovery,
    "patch_deployment": patch_deployment,
    "storage_expansion": storage_expansion,
    "baseline_capture": baseline_capture,
    "baseline_audit": baseline_audit,
    "baseline_remediate": baseline_remediate,
}


def get_all_templates() -> dict[str, Any]:
    """Return built-in + user-defined custom templates.

    Custom templates from ~/.vmware/workflows/*.yaml are loaded on each call
    (supports hot-reload — drop a YAML, immediately available).
    """
    import logging

    from vmware_pilot.custom_loader import load_custom_templates

    all_templates = dict(BUILTIN_TEMPLATES)
    custom = load_custom_templates()
    # Custom templates can override built-ins (user takes precedence) — but
    # warn loudly so a stray YAML cannot silently replace a vetted built-in.
    shadowed = sorted(set(custom) & set(BUILTIN_TEMPLATES))
    if shadowed:
        logging.getLogger("vmware-pilot.templates").warning(
            "Custom workflow YAML shadows built-in template(s) %s — the "
            "custom version in ~/.vmware/workflows/ takes precedence. "
            "Rename the YAML file(s) if this is unintentional.",
            ", ".join(shadowed),
        )
    all_templates.update(custom)
    return all_templates


# Backward compat — TEMPLATES is still available but prefers get_all_templates()
TEMPLATES = BUILTIN_TEMPLATES
