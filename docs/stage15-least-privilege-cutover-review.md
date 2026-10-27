# Stage 15.3A — PostgreSQL least-privilege cutover pre-execution safety review

**Review date:** 2026-10-27 (UTC+8)  
**Scope:** read-only design/configuration review. No role, grant, credential, Compose, container, database, or business-record operation was performed.

## Recommendation

**NO-GO until the P1 gates below are resolved and separately approved.**

The proposed separation is a sound direction: a `NOLOGIN` group role, a
non-owner login role, explicit object grants, and an API-only Compose override
are materially safer than the present superuser runtime identity. The disposable
validation evidence is strong, but it is not a substitute for a controlled live
execution plan with a fresh backup, proven override selection, private secret
handling, and an independently executable rollback.

No P0 data-loss or wrong-target defect was demonstrated by this static review.
That does **not** authorize a live cutover.

## Materials reviewed

| Material | Review purpose |
| --- | --- |
| `AGENTS.md` | Security, transaction, backup, and verification requirements. |
| `infra/dev/compose.yaml` | Base project, service topology, ports, volume, and current API database configuration. |
| `infra/dev/compose.runtime.yaml` | Candidate API-only credential override. |
| `infra/dev/runtime-grants.sql` | Proposed role grant surface and explicit revocations. |
| `infra/dev/backup.py`, `infra/dev/test_backup.py` | Target safeguards, snapshot/backup behavior, and offline boundary coverage. |
| `infra/dev/validate_runtime.py`, `infra/dev/runtime_probe.py` | Disposable runtime-role and denied-operation validation. |
| `infra/dev/README.md` | Development topology and operator commands. |
| `docs/stage15-backup-recovery.md` | Backup identity, restore evidence, persistence, and recovery boundaries. |
| `docs/stage15-operational-readiness.md` | Candidate cutover and rollback sequence. |

Static commands reviewed or scheduled for this review are listed in the
Verification section. No command that connects to the development database,
changes Docker state, or reads a secret into output was run.

## Environment targeting assessment

### Configuration facts verified statically

- Compose project name is `asi-meal-dev`.
- The configured public development endpoint is
  `https://192.168.45.145:43873/`; only the `web` gateway publishes that port.
- `api`, `frontend`, and `db` are internal-only Compose services. PostgreSQL has
  no host port in the base configuration.
- The intended database/user in the base file are both `asi_meal_dev`.
- The named PostgreSQL volume is `dev_postgres`, which resolves to
  `asi-meal-dev_dev_postgres` under the declared Compose project.
- The candidate override changes only `api.environment.ASI_DATABASE_URL`; it
  does not add ports, volumes, networks, services, or database configuration.
- The override is inactive unless explicitly passed with both `-f` files or
  selected through `COMPOSE_FILE`.

### Prior runtime evidence, not re-executed in this review

Stage 15.2/15.3 documentation records read-only inspection of
`asi-meal-dev-db-1`, volume `asi-meal-dev_dev_postgres`, PostgreSQL 17.11, and
an API connection to `asi_meal_dev` on the internal `db` service. It also
records that the current API identity is the schema-owning PostgreSQL
superuser. This review did not re-inspect containers or the database, so those
claims remain historical evidence rather than fresh verification.

## Privilege assessment

### Strengths

- The intended runtime group must already exist as `NOLOGIN`, with all five
  dangerous role flags disabled before the grant transaction continues.
- The documented login role is non-superuser, cannot create roles/databases,
  cannot replicate, and does not bypass RLS.
- The script revokes broad `PUBLIC` access and grants only `CONNECT`, schema
  `USAGE`, table-specific CRUD, selected update columns, and sequence `USAGE`.
- It deliberately excludes changes to recorded offering/category prices,
  historical order snapshots, migration revision, and audit-event mutation.
- No runtime table ownership, `CREATE` on `public`, DDL, role management, or
  migration privilege is granted.
- The disposable probe records 17 denied administrative/destructive statements
  while exercising authentication, imports, menu work, orders, receipts,
  reports, audit reads, user management, session revocation, and visitor
  Finance behavior. The existing report records this as passed; it was not
  rerun in this review.

### Limitations and future maintenance

- Grants enumerate today's 19 public tables and known columns. A migration or
  new table/sequence/function will not automatically be usable by the runtime
  role. This is intentional least privilege, but every approved migration must
  include a reviewed grant delta and disposable runtime validation.
- `REVOKE ALL ON ALL FUNCTIONS ...` leaves no direct function execution grant
  to the runtime group. Existing trigger behavior passed in the recorded
  disposable probe. Any new direct SQL function call or trigger/function
  privilege dependency must be tested before a migration is deployed.
- The role can select authentication/session tables because ORM authentication
  requires them. Database access is therefore not a substitute for application
  authorization; Docker/DB operator access remains privileged.

## Credential handling assessment

The proposed password flow is appropriate only if the password is entered in
the interactive PostgreSQL `\\password` prompt and stored solely in the existing
ignored `infra/dev/.env`. It avoids command-line password arguments and does
not print a connection URL.

The current documented `.env` ACL is a blocking concern: prior Stage 15.3
inspection recorded inherited local access allowing broad read/modify access.
That is unacceptable before adding a second database credential. The candidate
override correctly fails closed when `DEV_API_DB_PASSWORD` is absent, but there
is not yet a sufficient proof that ordinary Compose invocations will select the
override after `COMPOSE_FILE` is edited.

The current privileged `asi_meal_dev` credential is deliberately retained for
administration, backups, and configuration rollback. It must not remain the
API's effective account after authorization of the cutover.

## Execution and checkpoint review

The eventual, separately authorized sequence should be:

1. Confirm exact Compose labels, base/override paths, DB volume, no PostgreSQL
   host binding, database identity, and absence of unreviewed consumers.
2. Create and restore-validate a new private development-only backup. Confirm
   `verification.json`, archive hash, and isolated restore result before any
   privilege/configuration change.
3. Copy the *current* `.env` into the verified private backup directory **before
   changing the file or its ACL**, then record base service health/identity.
4. Restrict `.env` and parent-directory access to the owner and SYSTEM; verify
   the resulting ACL, rather than assuming `Set-Acl` succeeded as intended.
5. In an interactive administrator PostgreSQL session, create the two roles,
   set the new login password via `\\password`, and stop if either name already
   exists or the identity check fails.
6. Apply the reviewed grant script to the exact development database. A failure
   must stop before API activation; the old API remains available.
7. Add only the runtime password and override-selection values to the private
   `.env`. Validate both explicit-file and ordinary Compose resolution without
   displaying resolved environment values.
8. Recreate only `api` with the reviewed base+runtime pair.
9. Prove the *running API's actual PostgreSQL identity* is `asi_meal_api` and
   its five dangerous flags are false. Health 200 alone is insufficient.
10. Run the pre-approved, non-mutating application acceptance set, compare
    authoritative counts/reports with the pre-cutover snapshot, and create a
    fresh backup/restore validation under the new API credential setup.

An API-only recreation may interrupt in-flight requests briefly. Operators
must not blindly retry an ambiguous order; reconcile its existing request key
and optimistic version first.

## Backup and rollback assessment

The documented backup helper has good targeting safeguards: it checks Compose
labels/config paths, exact volume, no DB host binding, the API container's
private effective database URL, database/user/server identity, archive
readability, and isolated restore comparison. Recorded evidence shows a
full-content, financial, and sequence comparison in a disposable restore.

The proposed availability rollback is viable **after the P1 gates are fixed**:
restore the pre-cutover `.env`, validate the base Compose file, and recreate
only the API. It preserves the named database volume and does not need a
database restore when no schema/business data were changed.

It is intentionally not a full grant reversal: the new roles and `PUBLIC`
revocations remain for review. That is safe for restoring the prior
superuser-backed API, but must be explicitly accepted. A future permission
rollback must be based on an inventory of pre-existing grants/consumers, not a
blind `GRANT ... TO PUBLIC` or role drop.

## Required cutover gates

All of the following must be observed and recorded during a separately approved
execution. Any failure means stop; after API recreation, use the configuration
rollback procedure.

- Fresh backup and isolated restore drill succeed; archive/manifest path is
  private and verified.
- `.env` backup exists and its private destination ACL is verified before
  editing/restricting the active file.
- Active `.env` and relevant parent directory grant no broad user-group read or
  modify access; no secret appears in history, logs, or command output.
- Explicit `docker compose -f compose.yaml -f compose.runtime.yaml config
  --quiet` passes, and ordinary `docker compose config --quiet` passes after
  `COMPOSE_FILE` activation. `config --services` must contain exactly the
  expected four services.
- Pre- and post-cutover source identity is `asi_meal_dev`; post-cutover API
  identity is specifically `asi_meal_api` with all five dangerous flags false,
  no schema/table ownership, and no DDL/role capability.
- API health, authenticated sign-in/out, CSRF/origin behavior, authorized
  read-only employee/menu/report/activity routes, and the existing report/Excel
  download path work. No live order needs to be created for this check.
- A controlled non-business privilege probe confirms administrative operations
  are denied; use a reviewed probe, never ad hoc SQL against records.
- Gateway, frontend, database, and API remain healthy; database data/financial
  reconciliation matches the fresh pre-cutover snapshot.
- The backup helper and isolated restore validation still work, and the rollback
  operator can locate and validate the prior `.env` without accessing secrets
  from terminal output.

## Findings

| Priority | Finding | Required resolution |
| --- | --- | --- |
| P0 | None demonstrated by the static review. | Maintain target/backup gates; no authorization follows from this result. |
| P1 | Current `.env` ACL was historically broad. Adding `DEV_API_DB_PASSWORD` before ACL remediation would expose a new runtime secret to unauthorized local identities. | Define and test owner/SYSTEM-only ACL for `.env` and its parent access; verify it before entering the new credential. |
| P1 | The documented sequence restricts `.env` before copying its prior contents. Although the owner is retained, failure or operator error can leave no independently verified rollback copy. | Copy and validate `compose.env.before-cutover` in the protected backup directory before ACL/configuration modification. |
| P1 | Override activation is not proven by the candidate file alone. `COMPOSE_FILE` behavior must be validated after editing `.env`; otherwise a later ordinary Compose command can silently restore the privileged API identity. | Add an execution gate for both explicit and ordinary `docker compose config --quiet`/service-set checks and actual API identity validation. |
| P1 | Rollback restores service configuration but deliberately leaves new roles and broad `PUBLIC` revocations. Unknown non-API consumers could remain affected. | Inventory all database consumers and record the accepted scope. Prepare a reviewed, baseline-specific grant/role recovery plan; never use a generic PUBLIC restore. |
| P1 | The documented post-restart proof says to recheck identity but gives no exact redacted command/tool. API liveness can succeed while the old credential is still active. | Specify a reviewed non-mutating identity/role-flag check that runs from the API container and emits only database/user/boolean flags, never its URL/password. |
| P2 | The grant set is intentionally finite and has no default-privilege strategy. Future schema changes can fail at runtime. | Make a reviewed grant-delta and disposable runtime-probe result a migration release requirement. |
| P2 | API-only restart can interrupt a request; the plan relies on existing request-key/version reconciliation. | State operator handling explicitly in the change window and post-cutover checklist. |
| P2 | Trigger/function behavior is supported by recorded disposable tests, but direct-function execution is not generally granted. | Retest if migrations introduce direct function calls or new trigger privilege assumptions. |

## Verification performed in this review

The following are static/offline checks only; they do not connect to the live
development database or change service state:

```powershell
cd C:\asi-meal-management
.\.venv\Scripts\python.exe -m py_compile infra/dev/backup.py infra/dev/validate_runtime.py infra/dev/runtime_probe.py
.\.venv\Scripts\python.exe -m unittest infra/dev/test_backup.py
git diff --check
```

The following recorded Stage 15.3 evidence was reviewed, not rerun: 155
backend PostgreSQL tests passed; the isolated runtime probe passed normal HTTP
workflows plus 17 denied privilege checks; post-grant backup/restore validation
passed. These are relevant confidence signals, not proof of the present live
environment or authorization to modify it.

## Approval requirements and expected impact

Before a cutover can be authorized, the owner/operator must approve: the
credential ACL change, the new runtime credential, `PUBLIC` grant revocations,
the explicit service-consumer inventory, a fresh verified backup, the revised
rollback semantics, and a brief API-only interruption. The intended impact is
limited to API reconnection; the gateway, frontend, PostgreSQL container,
volume, schema, business records, and protected deployment remain untouched.

This review changed only this document.
