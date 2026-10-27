# Stage 15.3A.1 — Database cutover safeguard remediation

**Date:** 2026-10-27 (UTC+8)  
**Environment in scope:** `asi-meal-dev`, `https://192.168.45.145:43873/`,
database `asi_meal_dev`  
**Boundary:** preparation and isolated validation only. No live database query,
role/grant/credential/ACL change, Compose activation, API restart, or business
record change was performed.

## Recommendation

**CONDITIONAL GO for a separately approved cutover window only.**

The five P1 design gaps from the Stage 15.3A review now have an implemented
offline safeguard, an explicit documented procedure, and synthetic or isolated
validation evidence. The live-only gates in this document remain mandatory;
they cannot be satisfied in a preparation stage.

## P1 resolutions

| Prior finding | Remediation |
| --- | --- |
| Broad `.env` access before introducing the runtime password | Documented owner/SYSTEM/local-Administrators ACL procedure, with protected ACL verification and an isolated synthetic test. The real `.env` was not inspected or changed. |
| Rollback copy was made after ACL changes | The cutover sequence now copies first, refuses an existing target, verifies SHA-256 equality and independent readability, then changes ACLs. |
| Runtime override selection was ambiguous | `compose.runtime.yaml` is the only candidate override. The approved convention uses explicit `--env-file .env -f compose.yaml -f compose.runtime.yaml` for every restricted-runtime command; no `COMPOSE_FILE` is stored in `.env`. |
| No concrete proof of the API's live database identity | `infra/dev/runtime_identity.py` privately reads the API container's already-configured URL, performs a read-only role query, and prints only an allow-listed identity record. It has no HTTP route and refuses a non-Compose/non-running API container. |
| Rollback scope and non-API consumer impact unclear | A consumer inventory and explicit configuration-only rollback boundary are recorded below. PUBLIC revocations/roles are deliberately not silently reversed. |

## Synthetic ACL and rollback configuration procedure

The following sequence is for a future approved change window only. It must be
run from `C:\asi-meal-management\infra\dev` after the fresh backup/restore
drill has returned a verified private backup directory. It does not print the
contents of `.env`.

1. Confirm the backup directory is under `C:\asi-meal-management\backups`, is
   not a reparse point, has a valid `verification.json`, and has a protected
   private ACL.
2. Define `$preCutover` as that exact directory. Refuse the operation if
   `compose.env.before-cutover` already exists there.
3. Copy `.env` to that new destination, compare SHA-256 values, and open the
   destination for read-only access. A hash/read failure is a stop condition.
4. Apply a protected file ACL containing only the current owner SID, `SYSTEM`
   (`S-1-5-18`), and local `Administrators` (`S-1-5-32-544`), all with Full
   Control. Verify inheritance is disabled and the actual allow-list matches.
5. Review the parent directory independently. A protected file ACL does not
   alone prevent privileged directory-level administration; Docker
   administrators also remain able to inspect container environment values.

The exact future command block is maintained in
[`stage15-operational-readiness.md`](stage15-operational-readiness.md). Its
rollback restores the copied `.env`, verifies the rollback hash, validates the
base Compose configuration, then recreates **only** the API with the base file.

### Synthetic evidence

`infra/dev/test_cutover_safeguards.ps1` creates a GUID-named temporary directory
and a literal `SYNTHETIC_ONLY=placeholder` fixture. It applies the three-SID
ACL, makes a new protected rollback directory, refuses overwrites, checks the
copy hash, independently opens the copy, restores to a second synthetic file,
and checks its hash. It has no path or switch that targets `infra/dev/.env`.

Tested command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\dev\test_cutover_safeguards.ps1
```

Result: `Synthetic ACL, rollback backup, and restore verification passed.`

## Compose override contract

The candidate file is `infra/dev/compose.runtime.yaml`. It changes only
`api.environment.ASI_DATABASE_URL`, selecting `asi_meal_api` on the internal
`db:5432/asi_meal_dev` target. It does not modify services, ports, networks,
volumes, PostgreSQL initialization, or the web/frontend configuration.

`infra/dev/validate_compose_runtime.py` creates a temporary environment file
with synthetic passwords and runs only `docker compose config --format json`.
It compares:

- base configuration;
- the explicit two-file invocation; and
- the documented ordinary-command model with `COMPOSE_FILE` supplied only to
  that temporary process.

It rejects a different service set, any non-API service change, network/volume
change, an API change other than the URL, or a URL not using the restricted
username/host/database. It never prints the resolved configuration or either
synthetic password.

Tested command:

```powershell
.\.venv\Scripts\python.exe infra\dev\validate_compose_runtime.py
```

Result: candidate Compose contract passed with synthetic credentials; no service
was changed.

### Required deployment convention

Do not rely on ambient `COMPOSE_FILE` state. During the restricted-runtime
operation, use this exact form for `config`, `ps`, logs, and API recreation:

```powershell
docker compose --env-file .env -f compose.yaml -f compose.runtime.yaml <command>
```

For rollback, use the copied base `.env` and this exact base-only form:

```powershell
docker compose --env-file .env -f compose.yaml <command>
```

The API must be recreated only after the explicit runtime configuration passes
`config --quiet`. The base-only form is intentionally unable to select the
runtime override.

## Runtime identity proof

`infra/dev/runtime_identity.py --post-cutover` is an operator-only, read-only
post-restart check. It:

1. Inspects only `asi-meal-dev-api-1` and rejects mismatched Compose project,
   service, config-file pair, or stopped containers.
2. Executes a short Python worker inside that API container, where the existing
   `ASI_DATABASE_URL` is already available.
3. Parses the URL only in-process, validates internal host/database shape,
   opens a read-only identity query, and emits only database name, role name,
   five role flags, and public-table ownership count.
4. Fails unless the database is `asi_meal_dev`, user is `asi_meal_api`, all
   dangerous flags are false, and owned public tables equal zero.

It cannot be called accidentally without `--post-cutover`, accepts no database
URL/password argument, and exposes no diagnostic HTTP endpoint. The expected
success record contains no secret, employee, order, or session data.

The same `evaluate_identity` contract is imported by the disposable
`runtime_probe.py`, so the post-cutover checker and test probe do not drift.
The final isolated validation restored the existing verified archive only into a
temporary PostgreSQL container with tmpfs storage and no network access to the
development stack. It passed with runtime `asi_meal_api`, all five flags false,
zero ownership, 17 denied privileged-operation probes, normal authenticated
workflows, and a subsequent backup/restore validation. The temporary container
is removed by the existing restore harness. No live database connection was
made.

## Database consumer inventory

| Consumer | Database identity/configuration | Effect of PUBLIC revocation / required boundary |
| --- | --- | --- |
| FastAPI runtime | `ASI_DATABASE_URL` in `infra/dev/compose.yaml`; candidate override replaces only this value with `asi_meal_api`. | Primary consumer. Must use explicit grants and pass identity proof after restart. |
| Alembic migration commands | Explicit shell `ASI_DATABASE_URL`; `alembic/env.py` refuses a missing/non-PostgreSQL URL. | Must use the controlled owner/migration identity, never the runtime role. Every migration needs a reviewed grant delta. |
| Backup helper | Privately parses the API runtime URL for a read-only snapshot; local DB-container `pg_dump` uses the initialization administrator. | Runtime needs complete read access; administrator remains available for dump/restore. |
| Restore/runtime validation | Fresh tmpfs PostgreSQL with generated `restore_operator` and ephemeral restricted test role. | Disposable only; it never targets `asi_meal_dev` or its volume. |
| Administrative account CLI | Reads explicit shell `ASI_DATABASE_URL` and is intended for controlled administration. | Must not be run using the application runtime credential unless separately reviewed. |
| Demo seed/client | Uses authenticated HTTP calls; its target guard inspects an operator-supplied URL for the old isolated demo, not this Compose stack. | Not a direct consumer of this development database in the documented workflow. |
| Backend tests | Disposable PostgreSQL fixture credentials and migration test configuration. | No live dependency; grant regressions are tested in the separate restore harness. |
| Frontend/Excel/PDF export | Calls the API only; no direct PostgreSQL URL/configuration. | Indirectly affected only if API grants are incomplete. |
| Scheduled jobs/maintenance services | No scheduler or extra development Compose service was found in the reviewed configuration. | Re-evaluate this inventory before adding one. |
| `infra/compose.yaml` | Separate non-development Compose configuration with separate variables. | Out of scope; never select or modify it during this cutover. |

## Rollback boundary

An availability rollback is **configuration only**:

1. Restore the protected `compose.env.before-cutover` copy over `.env`.
2. Compare its SHA-256 with the protected copy.
3. Validate `--env-file .env -f compose.yaml config --quiet`.
4. Recreate only the API using the base Compose file.
5. Verify base API health/sign-in behavior; record that it intentionally returns
   to the old overprivileged database identity.

The PostgreSQL volume, schema, business records, backup archives, gateway,
frontend, and database container are preserved. A database restore is neither
needed nor appropriate for this availability rollback.

The new roles and `PUBLIC` revocations remain in place deliberately. A separate
database-security rollback is required only if the consumer inventory proves a
non-API consumer needs the former grants. It must begin with a baseline grant
inventory and be separately approved; never repair it with blanket `PUBLIC`
grants or automatic role deletion.

## Verification performed

```powershell
.\.venv\Scripts\python.exe -m py_compile infra\dev\runtime_identity.py infra\dev\runtime_probe.py infra\dev\validate_compose_runtime.py
.\.venv\Scripts\python.exe -m unittest infra\dev\test_backup.py infra\dev\test_runtime_identity.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\dev\test_cutover_safeguards.ps1
.\.venv\Scripts\python.exe infra\dev\validate_compose_runtime.py
.\.venv\Scripts\python.exe infra\dev\validate_runtime.py --backup backups\asi-meal-dev-20261027T053346Z-bf583cc1\database.dump
git diff --check
```

Results: Python syntax passed; 8 offline Python tests passed; synthetic ACL/
rollback test passed; synthetic Compose contract passed; and the final isolated
runtime validation passed. The restore harness reported 12 safe sequences,
identical table/content/financial comparison, normal workflows, and post-grant
backup/restore success. The archive was used only as input to a disposable
restore; no service/database operation targeted the running development stack.

## Remaining issues and authorization gates

| Priority | Item |
| --- | --- |
| P0 | None demonstrated in this preparation stage. |
| P1 | A fresh backup plus isolated restore drill must pass immediately before the live cutover. |
| P1 | The real `.env` and parent directory must be ACL-reviewed and remediated in the approved window; synthetic success is not proof of its current ACL. |
| P1 | Confirm no additional database consumers exist at execution time and explicitly accept the persistent role/PUBLIC-grant state after configuration rollback. |
| P1 | Run explicit Compose validation and `runtime_identity.py --post-cutover` after the API-only recreation; health 200 is insufficient. |
| P2 | Add migration-release grant-delta review and rerun the disposable probe whenever models, sequences, or direct SQL functions change. |
| P2 | Document and rehearse request-key/version reconciliation for a request interrupted by the API-only restart. |

No live cutover is authorized by this document.
