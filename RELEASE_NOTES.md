# VMware Pilot — Release Notes

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
