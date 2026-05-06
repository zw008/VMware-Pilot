## v1.5.19 (2026-05-06)

**Family alignment** — no source changes in this orchestration skill.

- **align:** Catching up to family v1.5.19 (was at v1.5.17). Tracks fixes in vmware-nsx (CRITICAL CLI imports), vmware-vks (ApiClient leak), vmware-harden (Twin indexes + LEFT JOIN report), vmware-policy (approval gate AND→OR + singleton lock). yjs review 2026-05-06.
- **smoke:** Family `scripts/family_smoke.sh` adds Check 3b — recursive `--help` on every subcommand to surface broken lazy imports (CLAUDE.md 踩坑 #27).

## v1.5.17 (2026-05-01)

**v2 architecture follow-ups** — implements 4 of 5 additive gaps identified in the v1.5.16 architecture audit (`docs/architecture-audit-2026-04-30.md`).

- **feat:** New `investigate_alert` template — causal-chain root-cause workflow that codifies the four-criteria completeness check (falsifiability/sufficiency/necessity/mechanism) from the EHE investigation protocol. Round 1 parallel-gathers alarms + events + Aria alerts, then pauses for synthesis. Optional `deep_dive=True` adds a second round of broader gathering.
- **feat:** New `review_workflow` MCP tool — structural sanity check before execution. Detects delete-then-use cycles, ungated destructive operations, placeholder parameters, non-contiguous parallel groups, destructive ops inside parallel groups. Returns `verdict: approved | needs_revision` plus per-finding severity, kind, and message.
- **feat:** `WorkflowStep.group_id` field + `parallel_group(group_id, steps)` helper — siblings sharing a non-empty group_id may be dispatched concurrently by the calling agent. Backward-compatible deserialization for pre-existing workflows.
- **docs:** SKILL.md and `references/integration-patterns.md` now document the dispatch contract explicitly: pilot is the dispatcher (plans, state, approval gates), the calling AI agent is the executor (invokes per-step MCP tools).
- **align:** Family version bump to v1.5.17.

Tests: 75 → 96 passing (4 parallel_group + 7 investigate_alert + 10 review). MCP tools: 11 → 12. Templates: 14 → 15.

## v1.5.16 (2026-04-30)

**Enterprise Harness Engineering alignment** — adapted from the Linkloud × addxai framework articles ([part 1](https://mp.weixin.qq.com/s/hz4W7ILHJ1yz_pG0Z1xP-A), [part 2](https://mp.weixin.qq.com/s/F3qYbyB3S8oIqx-Y4BrWNQ)).

- **docs:** New `docs/architecture-audit-2026-04-30.md` — verifies pilot already follows the v2 Dispatcher + one-shot subagent pattern from EHE; identifies 5 additive gaps tracked as separate work items (G1-G5: investigate template, review gate, parallel step, L5 hooks, dispatch contract docs).
- **align:** Family version bump 1.5.14 → 1.5.16 (skipping 1.5.15 to align with the rest of the family).

## v1.5.14 (2026-04-21)

- Align with VMware skill family v1.5.14 (code review follow-up fixes by @yjs-2026)

## v1.5.13 (2026-04-21)

**Bug fixes from code review 2026-04-20**

- **fix(P0):** `executor.py` — added `_resolve_step_refs()` for step-to-step variable substitution; `plan_and_approve` workflow no longer passes literal `__from_step_0__` as plan_id
- **fix:** `templates.py` — `clone_and_test` now accepts both `memory_mb` and `memory_gb` in change_spec for reconfigure routing (was only checking `memory_mb` while docstring documented `memory_gb`)
- **fix:** `server.py` — `approve()` now rejects empty `approver` parameter with clear error message for audit trail integrity

# VMware Pilot — Release Notes

## v1.5.12 (2026-04-17)

**Bug fix from code review by @yjs-2026**

- **fix:** `rollback()` — persist workflow state after entering ROLLING_BACK and after each rollback step, preventing state inconsistency if process crashes mid-rollback

## v1.5.11 (2026-04-17)

- Align with VMware skill family v1.5.11 (AVI 22.x fixes from @timwangbc)

## v1.5.10 (2026-04-16)

- Security: bump python-multipart 0.0.22→0.0.26 (DoS via large multipart preamble/epilogue)
- Align with VMware skill family v1.5.10

## v1.5.8 (2026-04-15)

- Align with VMware skill family v1.5.8 (NSX/AVI/Aria/AIops bug fixes)

## v1.5.7 (2026-04-15)

- Fix: `plan_and_approve` workflow template used `__from_step_0__` as a literal placeholder string, causing `vm_apply_plan` to receive an invalid plan_id at execution. Executor now resolves `__from_step_N__` (full result) and `__from_step_N.field__` (nested field) references against completed steps' `result` at dispatch time. Also applied to rollback_params.
- Align with VMware skill family v1.5.7

## v1.5.6 (2026-04-15)

- Align with VMware skill family v1.5.6 (AVI bugfixes + packaging hotfix)

## v1.5.5 (2026-04-15)

- Align with VMware skill family v1.5.5

## v1.5.4 (2026-04-14)

- Security: bump pytest 9.0.2→9.0.3 (CVE-2025-71176, insecure tmpdir handling)

## v1.5.0 (2026-04-12)

### Anthropic Best Practices Integration

- **[READ]/[WRITE] tool prefixes**: All MCP tool descriptions now start with [READ] or [WRITE] to clearly indicate operation type
- **Read/write split counts**: SKILL.md MCP Tools section header shows exact read vs write tool counts
- **Negative routing**: Description frontmatter includes "Do NOT use when..." clause to prevent misrouting
- **Broadcom author attestation**: README.md, README-CN.md, and pyproject.toml include VMware by Broadcom author identity (wei-wz.zhou@broadcom.com) to resolve Snyk E005 brand warnings

## v1.4.9 (2026-04-11)

- Security: bump cryptography 46.0.6→46.0.7 (CVE-2026-39892, buffer overflow)
- Fix: require explicit "VMware" context in pilot workflow routing triggers
- Fix: clarify vmware-policy compatibility field (Python transitive dep, not required standalone binary)
- Remove stale dist/ build artifacts from git tracking
- Version aligned with VMware skill family (1.4.5 → 1.4.9)

## v1.4.5 — 2026-04-03

- **Security**: bump pygments 2.19.2 → 2.20.0 (fix ReDoS CVE in GUID matching regex)
- **Infrastructure**: add uv.lock for reproducible builds and Dependabot security tracking

## v1.4.0 — 2026-03-29

Initial release. Multi-step workflow orchestration with approval gates for VMware MCP skills.

- 11 MCP tools: design/plan/create/run/approve/rollback/status + discovery
- 4 built-in workflow templates: clone_and_test, incident_response, plan_and_approve, compliance_scan
- Interactive design mode: natural language → draft → edit → confirm → execute
- Custom YAML templates: drop in ~/.vmware/workflows/, hot-reload without restart
- State persistence: SQLite at ~/.vmware/workflows.db, survives restarts
- Approval gates: pause execution for human review before destructive operations
- Rollback: reverse completed steps in order on failure
- Skill catalog: 7 skills, 162 tools available for workflow composition
- blocked_by_policy state: mid-workflow policy denial without auto-rollback
- 32 unit tests