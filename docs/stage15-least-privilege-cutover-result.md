# Stage 15.3B — Controlled PostgreSQL least-privilege cutover result

**Date:** 2026-10-27 (UTC+8)  
**Result:** **BLOCKED — no cutover performed**

## Stage 15.3B retry — 2026-10-27 (UTC+8)

The owner authorized a retry after Stage 15.3B.1's DACL-only correction. This
retry also stopped before any live configuration, credential, role/grant,
container, schema, or business-record change.

Fresh retry preflight passed for the exact `asi-meal-dev` project, all four
expected services, `asi_meal_dev`, and volume `asi-meal-dev_dev_postgres`.
The synthetic DACL-only safeguard and synthetic Compose contract both passed.
HTTPS returned root/health/auth-me status 200/200/401. The current API identity
remained the original `asi_meal_dev` administrative role, and no candidate
runtime roles existed.

A new protected backup and isolated restore drill completed successfully before
the stopped ACL operation:

- Archive: `backups/asi-meal-dev-20261027T065533Z-fca539c3/database.dump`
- 19 tables and 12 sequence states matched the isolated restore.
- Received/Pending orders: 6/2; received sales/allocations: 1,470.00/1,470.00;
  Salary Deduction: 1,025.00; unbalanced Received orders: 0.
- The archive is retained and was never restored over the live database.

The corrected DACL-only procedure then verified target ownership before making
any write. It refused the operation because `infra/dev` is owned by a different
local SID (`...-1006`) than the authorized operator (`...-1001`), SYSTEM, or
the local Administrators group. Preserving ownership is an explicit safeguard;
the procedure must not silently take ownership or change it.

Read-only post-stop verification confirmed the fresh backup directory and
`.env` remain owned by the operator, no rollback-copy artifact was created, and
`asi_meal_api`/`asi_meal_runtime` remain absent. No ACL, credential, database,
role, grant, service, container, or volume change occurred in this retry.

**Required action before another retry:** an authorized Windows administrator
must decide whether the existing `infra/dev` owner SID is an approved operator
identity. If ownership must change, that is a separate, explicitly approved
Windows ownership operation with its own rollback record; this cutover must not
take ownership implicitly. After resolution, start again with a new preflight
and new backup/restore drill.

## Confirmed environment identity

Read-only preflight identified the authorized development stack only:

- Compose project: `asi-meal-dev`
- Gateway: `asi-meal-dev-web-1`, HTTPS mapped only to
  `192.168.45.145:43873` and `127.0.0.1:43873`
- API: `asi-meal-dev-api-1`, healthy
- Frontend: `asi-meal-dev-frontend-1`, healthy
- PostgreSQL: `asi-meal-dev-db-1`, PostgreSQL 17, healthy
- Database/current API identity: `asi_meal_dev` / `asi_meal_dev`
- Persistent volume: `asi-meal-dev_dev_postgres`, mounted at
  `/var/lib/postgresql/data`
- PostgreSQL has no host-published port. API/frontend/database are internal;
  only the gateway publishes the development HTTPS endpoint.

The current API role remained the existing superuser with database/role creation,
replication, and RLS-bypass flags. Neither `asi_meal_api` nor
`asi_meal_runtime` existed before or after the stopped operation.

## Preflight and recovery evidence

The base Compose configuration resolved successfully. HTTPS checks returned:

- `/`: 200
- `/health`: 200
- `/auth/me`: 401 without a session, as expected

A fresh protected backup and isolated restore drill completed before the blocked
configuration-protection step:

- Archive: `backups/asi-meal-dev-20261027T063818Z-a20d61e3/database.dump`
- Archive readability and SHA-256 verification: passed
- Restore target: temporary, network-isolated PostgreSQL with tmpfs storage
- Compared tables: 19, with matching full-content fingerprints
- Safe sequences: 12
- Received orders / Pending orders: 6 / 2
- Received sales / allocations: 1,470.00 / 1,470.00
- Salary Deduction: 1,025.00
- Invalid constraints / unbalanced received orders: 0 / 0
- Alembic revision: `0005_password_change_required`

The archive remains retained. It was never restored over the running database.

## Blocking safeguard failure

The mandatory ACL-protection step stopped while attempting to apply the approved
protected ACL to the **new backup directory**, before copying or changing
`infra/dev/.env`:

```text
Set-Acl: The process does not possess the 'SeSecurityPrivilege' privilege
which is required for this operation.
```

The task's mandatory-stop rule applies. No attempt was made to bypass the
Windows security control, weaken the ACL, change roles/grants, generate/store a
runtime password, activate the Compose override, or restart the API.

Post-stop read-only verification confirmed:

- No `compose.env.before-cutover` copy, hash, or ACL metadata artifact was
  created in the new backup directory.
- `infra/dev/.env` remains unprotected/inherited; it was not changed.
- The `infra/dev` parent directory remains unprotected/inherited; it was not
  changed.
- `asi_meal_api` and `asi_meal_runtime` remain absent.
- Root/health/auth status remained 200/200/401.

## Role/grant and service changes

**None.** No PostgreSQL role, grant, revocation, password, schema, migration,
business record, or database content was changed. The gateway, frontend, API,
PostgreSQL service, and persistent volume were preserved; no container was
recreated or restarted.

## Required next approval/action

An authorized Windows administrator must first resolve the ACL capability under
the intended operator account. The minimum diagnostic is:

```powershell
whoami /priv | Select-String 'SeSecurityPrivilege|SeRestorePrivilege|SeTakeOwnershipPrivilege'
```

Do not rerun the cutover until an administrator has confirmed why the protected
ACL operation requires `SeSecurityPrivilege` on this host and can execute the
documented owner/SYSTEM/Administrators ACL procedure without excluding the
operator or Docker Desktop. Re-run the complete preflight and create a new fresh
backup after that capability is available; do not reuse this blocked attempt as
authorization to skip the backup or ACL gates.

## Residual risks

- The running API still uses the broad `asi_meal_dev` superuser identity.
- The current `.env` and parent directory retain inherited broad access.
- No runtime credential exists and the runtime Compose override remains inactive.
- The fresh backup improves recoverability but does not remove the above
  least-privilege/secret-file risks.

## Files changed

Only this result document was added during Stage 15.3B. Existing uncommitted
Stage 15.2/15.3 preparation files were preserved.
