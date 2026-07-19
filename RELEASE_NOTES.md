## v1.8.1 (2026-07-19) — read-only mode reaches the surfaces that teach it

v1.8.0 put read-only mode in the code and documented it in the README only.
Every other layer was empty, and each serves a different reader: SKILL.md is what
the agent loads, setup-guide is what an operator reads while configuring, `doctor`
is where they verify it took. The gap had two concrete costs.

An agent read SKILL.md, called a write tool the gate had withheld, and got nothing
back — with no way to learn that the absence was a deliberate lockdown rather than
a fault. It reads as a broken tool, so the model retries or hunts for a workaround.

An operator who set the switch had no way to confirm it. The only signal was a line
in the MCP server's start-up log.

### Added — the feature is now documented where each reader looks

SKILL.md, setup-guide and capabilities now cover read-only mode. Pilot's case is
the counter-intuitive one and is called out explicitly: **orchestration is its write
surface.** Read-only withholds 9 of 13 tools, leaving only the 4 query tools — a
read-only pilot cannot author, plan, run, approve, roll back or cancel anything.
Env vars are the only switch here; this package has no config file.

## v1.8.0 (2026-07-18) — read-only mode, working policy defaults, declared environments

Family release driven by [VMware-AIops#31](https://github.com/zw008/VMware-AIops/issues/31),
where an operator running Llama 3.3 70B (Goose / OpenShift AI, on-prem H100) had to
hand-write 17 prompt guardrails to make tool calling reliable. A prompt is advisory — a
model can ignore it. Every guardrail that could move into the harness has.

### Added
- **Read-only mode.** Set `VMWARE_PILOT_READ_ONLY=true` (or the family-wide
  `VMWARE_READ_ONLY=true`) and every write tool is removed from the MCP registry
  at start-up. `list_tools()` never offers them, so the model cannot call what it cannot
  see. **Off by default** — nothing changes unless you turn it on. Fail-closed: if the
  mode is requested but cannot be guaranteed, the server refuses to start rather than
  running open. vmware-pilot reads no config file, so these environment variables are the
  only switch — there is no `read_only:` config key here.
- **Declared environment for policy scoping.** Policy rules scope by environment. Pilot
  owns no targets and no connection, so it registers a constant `local` rather than
  reading `environment:` from a config target the way the connected skills do. Its writes
  land in the local workflow DB; the approval gate on the real change applies downstream,
  in the target skill's process, against that skill's declared environment.

### Changed — migration, read this
- **Approval tiers now actually run.** They shipped in v1.6.0 but the engine only ever
  read `~/.vmware/rules.yaml`, and a fresh install has no such file — so every deny rule,
  maintenance window and approval tier had been inert on every install that never
  hand-authored one. A packaged baseline now loads when you have written no rules of your
  own. Writes at medium risk and above are stamped with their tier in the audit log;
  irreversible work and guest execution against a target declared `production` require a
  named approver via `VMWARE_AUDIT_APPROVED_BY`.
- **`environment:` will become required for writes — no action needed in pilot.** A
  state-changing operation against a target that declares no environment runs with a
  warning today, and the next major release refuses it. That requirement lands on the
  skills that own targets; pilot owns none and reports a constant `local`, so it is
  unaffected either way. Declare `environment:` in the config of each connected skill
  (aiops, monitor, nsx, …) and check what applies before upgrading:
  `vmware-audit policy --operation vm_delete --env <env>`.

### Fixed
- **Policy glob patterns with a leading wildcard silently matched nothing.** A rule written
  `operations: ["*_delete"]` parsed fine, read correctly, and never fired — only a trailing
  `*` was honoured. Now full glob matching, for operations and environments alike.

### Notes
- Requires `vmware-policy>=1.8.0`; publish that package first.
- `vmware-audit policy` reports which rules are in force and where they came from —
  including the case where your rules file exists but failed to parse, which previously
  looked identical to "policy is working".

### Fixed — pre-release review (2026-07-19)

- **`get_skill_catalog` now lists `avi`.** The docs advertise cross-skill AVI workflows
  ("drain server, patch, restore traffic") but the design catalog carried no avi entry,
  so an agent calling `get_skill_catalog` to design exactly that workflow got zero avi
  tools. 13 curated tools added; the catalog is now 69 across 8 skills.
- **Tool and template tables were short.** `capabilities.md` listed 11 of 13 MCP tools
  (missing `review_workflow`, `cancel_workflow`) and 14 of 15 built-in templates
  (missing `investigate_alert`).
- **Removed `config.example.yaml`.** All four keys were inert — `database` and
  `templates_dir` are hardcoded constants with no config or env override, and
  `policy_rules` / `audit_db` belong to vmware-policy. It told operators to copy a file
  to a path nothing reads.

## v1.6.2 (2026-06-24) — MCP Registry registration

Adds the `mcp-name` marker to the README so the package can register on the MCP Registry (踩坑 #31). No functional code changes.

## v1.6.1 (2026-06-24) — version alignment

No functional changes — version bumped to stay aligned with the VMware skill family release.

## v1.5.38 (2026-06-12) — backlog finish: cancel_workflow, templates split

### Added
- **`cancel_workflow` MCP tool** + a terminal `CANCELLED` state. An approval-rejected or cancelled
  workflow can no longer be run — `run_workflow`/`resume_after_approval` refuse it with a teaching error,
  and cancel is itself audited. Closes a gap where a rejected PENDING workflow could still execute. (#7)

### Changed
- Split `templates.py` (1156 lines) into a `templates/` package and the MCP server into `tools/*`, all
  under the 800-line cap; builtin template names/IDs unchanged. (#8)

## v1.5.37 (2026-06-12) — backlog: remove dead states

### Changed
- Removed never-assigned workflow states (`MONITORING`, `COMMITTING`, `BLOCKED_BY_POLICY`) and the
  unreachable `mark_blocked`; verified no persisted state could carry them. (#9)

## v1.5.36 (2026-06-12) — never report work that wasn't performed

### Fixed
- **No-op "completed" workflows eliminated** — with no real dispatcher wired, the executor recorded
  every step as success and marked the workflow COMPLETED. Steps are now `not_executed` and the run
  finishes `dispatch_required` with a pending-step list; `COMPLETED` requires genuine execution.
- **Redacted secrets can't be silently dispatched** — a workflow resumed in a fresh process loaded
  `***` placeholders; dispatch now halts with a teaching error telling the operator to re-source them.
- **Crash-resume no longer skips an in-flight step as done** — a `running` step on resume is marked
  `interrupted` and the run halts with a verify-then-retry/rollback message.
- **Approval gating is now enforced** (not advisory) — ungated destructive workflows are refused
  unless `force=True` (audited).
- Step-ref resolution raises on invalid/forward refs instead of passing a literal placeholder;
  rollback outcomes are persisted; illegal state transitions rejected.

## v1.5.35 (2026-06-10) — security hardening: don't persist secrets; lock down state

### Fixed
- **Workflow params are redacted before SQLite persistence** — passwords/tokens stay
  in memory for the running workflow but are never written to `~/.vmware/workflows.db`.
- **State storage** dir is 0700 and the DB (incl. WAL/SHM) is 0600.
- **Custom-workflow `name`** is validated against path traversal before becoming a
  filename; the workflows dir is created 0700.

This release aligns the whole family back to a single version (1.5.35); vmware-policy and vmware-pilot return to the shared number after sitting at 1.5.22.

## v1.5.22 (2026-05-08)

**Smithery onboarding** — `vmware-pilot` is now installable via Smithery.

- **feat:** Added `Dockerfile` (Python 3.12-slim + uv) for containerized stdio MCP server.
- **feat:** Added `smithery.yaml` declaring stdio transport + config schema for the Smithery registry.
- **feat:** Added `mcp_server/__main__.py` so `python -m mcp_server` works inside the container.
- **align:** Tracks v1.5.22 family bump.

## v1.5.21 (2026-05-08)

**Family alignment** — no source changes in this skill. Skipped v1.5.20 family bump; this is the catch-up release.

- **deps:** Bumped `python-multipart` 0.0.26 → 0.0.27 (transitive, fixes GHSA HIGH DoS via unbounded multipart headers).
- **align:** Tracks family v1.5.20 + v1.5.21 alignment.

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