"""vmware-pilot declares a constant environment, and must keep doing so.

Policy rules scope by environment. The baseline treats a target that declares
none as unknown: today a state-changing operation against it runs but logs a
warning (``require_declared_environment: warn``), and the next major release
refuses it outright (``true``).

Every skill with a config answers this per target. vmware-pilot has none — it
orchestrates other skills and owns no connection — so it registers a constant
``local`` resolver instead. That is sound because pilot's own writes land in
the local workflow DB, never on a VMware estate: the executor does not call
VMware APIs, and with no dispatch function configured (the shipped MCP server's
state) executable steps are recorded as ``not_executed``. The approval gate on
the real infrastructure change is not skipped — it happens downstream, in the
target skill's process, against that skill's declared environment.

Why this file exists: under today's warn setting a missing registration is
INVISIBLE. Every pilot write would still run; the only symptom would be a log
line. It would surface for the first time when the enforcing release lands and
bricked every workflow tool at once. So the registration is pinned here, and a
refactor that drops it fails loudly and immediately instead.
"""

from __future__ import annotations

import importlib

import pytest

import vmware_policy.environment as env_mod
from mcp_server import server
from vmware_policy.environment import resolve_environment, set_environment_resolver
from vmware_policy.policy import get_policy_engine, reset_policy_engine


@pytest.fixture()
def baseline():
    """The shipped policy baseline — currently the warn-only migration setting."""
    reset_policy_engine()
    get_policy_engine()
    yield
    reset_policy_engine()


@pytest.fixture()
def enforcing(tmp_path):
    """The same rules with the requirement switched on, as the next major
    release will ship it. This is the setting that makes a lost registration
    fatal, so pilot's behaviour under it is the point of this file."""
    rules = tmp_path / "rules.yaml"
    rules.write_text("require_declared_environment: true\n")
    reset_policy_engine()
    get_policy_engine(rules)
    yield
    reset_policy_engine()


@pytest.fixture(autouse=True)
def _restore_resolver():
    """Tests here clear/reload the global resolver; put it back afterwards."""
    yield
    importlib.reload(server)


@pytest.mark.unit
class TestConstantResolverIsRegistered:
    def test_importing_the_server_registers_a_resolver(self) -> None:
        set_environment_resolver(None)
        importlib.reload(server)

        assert env_mod._resolver is not None, (
            "mcp_server.server must call set_environment_resolver() at import. "
            "Without it every pilot write reads as undeclared — invisible under "
            "today's warn setting, and a total block once enforcement lands."
        )
        assert env_mod._resolver is server._environment_for

    def test_resolver_reports_a_non_empty_environment(self) -> None:
        importlib.reload(server)

        # "" is the sentinel for *undeclared*. Anything else is a declaration.
        assert resolve_environment("") != ""
        assert resolve_environment("anything") == server.LOCAL_ENVIRONMENT

    def test_declaration_is_constant_across_targets(self) -> None:
        """Pilot has no per-target knowledge, so it must not pretend to."""
        importlib.reload(server)

        for target in ("", "prod-vc01", "vcenter-lab", "nonsense"):
            assert resolve_environment(target) == server.LOCAL_ENVIRONMENT

    def test_declared_environment_is_not_a_production_label(self) -> None:
        """`local` must not collide with the environments real rules scope to.

        If pilot claimed `production`, its every workflow edit would demand a
        named approver; if it claimed a name an operator also uses for a real
        estate, rules would cross-apply. `local` is deliberately neither.
        """
        assert server.LOCAL_ENVIRONMENT not in ("production", "prod", "staging", "")


@pytest.mark.unit
class TestWritesAreNotBlocked:
    """The consequence that actually matters: pilot's tools keep working."""

    @pytest.mark.parametrize("mode", ["baseline", "enforcing"])
    def test_workflow_authoring_write_runs(self, mode, request, tmp_path) -> None:
        request.getfixturevalue(mode)
        importlib.reload(server)

        from vmware_pilot.models import WorkflowStore

        server._store = WorkflowStore(db_path=tmp_path / "workflows.db")
        server._executor = None
        try:
            result = server.create_workflow(
                name="env_check",
                description="d",
                steps=[
                    {
                        "action": "a",
                        "skill": "monitor",
                        "tool": "get_alarms",
                        "params": {},
                    }
                ],
            )
        finally:
            server._store = None
            server._executor = None

        assert "error" not in result, result

    @pytest.mark.parametrize("mode", ["baseline", "enforcing"])
    def test_medium_risk_operation_is_allowed_by_policy(self, mode, request) -> None:
        request.getfixturevalue(mode)
        importlib.reload(server)

        result = get_policy_engine().check_allowed(
            "create_workflow",
            env=resolve_environment(""),
            risk_level="medium",
        )
        assert result.allowed is True
        assert result.rule != "undeclared_environment_warning"

    @pytest.mark.parametrize("risk", ["medium", "high"])
    def test_every_write_risk_level_is_allowed_when_enforcing(
        self, enforcing, risk
    ) -> None:
        """rollback/cancel are high risk — they must not be blocked either."""
        importlib.reload(server)

        result = get_policy_engine().check_allowed(
            "rollback", env=resolve_environment(""), risk_level=risk
        )
        assert result.allowed is True


@pytest.mark.unit
class TestMissingRegistrationWouldBlockWrites:
    """Proves the pin above is load-bearing rather than decorative.

    If it were not registered, pilot would read as undeclared — and under the
    enforcing release that is a refusal. This is the failure the registration
    prevents.
    """

    def test_without_a_resolver_writes_are_refused_when_enforcing(
        self, enforcing
    ) -> None:
        set_environment_resolver(None)

        result = get_policy_engine().check_allowed(
            "create_workflow", env=resolve_environment(""), risk_level="medium"
        )
        assert result.allowed is False
        assert result.rule == "undeclared_environment"

    def test_without_a_resolver_writes_only_warn_today(self, baseline) -> None:
        """And why the enforcing fixture is needed to catch it: under the
        shipped setting the same mistake is silent."""
        set_environment_resolver(None)

        result = get_policy_engine().check_allowed(
            "create_workflow", env=resolve_environment(""), risk_level="medium"
        )
        assert result.allowed is True
        assert result.rule == "undeclared_environment_warning"


@pytest.mark.unit
class TestReadsAreNeverGated:
    @pytest.mark.parametrize("mode", ["baseline", "enforcing"])
    def test_reads_allowed_with_no_resolver_at_all(self, mode, request) -> None:
        request.getfixturevalue(mode)
        set_environment_resolver(None)

        assert get_policy_engine().check_allowed(
            "list_workflows", env="", risk_level="low"
        ).allowed
