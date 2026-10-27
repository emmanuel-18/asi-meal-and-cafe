# Stage 15.3 — Operational readiness and database security

Assessment: 2026-10-27, UTC+8. Development:
`https://192.168.45.145:43873/`, Compose project **asi-meal-dev**.

## Result and boundary

The candidate non-superuser grants passed authenticated application workflows
against a fresh isolated restore of the verified Stage 15.2 archive. Seventeen
prohibited SQL operations were denied. A post-grant backup was itself fully
restored and compared in another disposable instance.

**No live roles, grants, credentials, configuration, file permissions, records
or services changed. No API restart/cutover occurred.** Candidate grants and the
inactive Compose override require separate owner approval. No scheduled jobs,
retention deletions, uploads, new migrations, commits or pushes. Prior work was
preserved. This is not a production-readiness certification.

## Verified configuration and actionable findings

Read-only Docker inspection reconfirmed project/configuration labels and the
same IDs as Stage 15.2: gateway `f1193b6a7a37`, frontend `68747b8cbc30`, API
`357dcaa681da`, DB `1688902589ad`. All are running; frontend/API/DB are healthy.
Configuration: `infra/dev/compose.yaml`; database/user `asi_meal_dev`; volume
`asi-meal-dev_dev_postgres`; internal DB network, no host database port.

Compose interpolates the ignored `.env`'s `DEV_DB_PASSWORD` into API
`ASI_DATABASE_URL`. Thus API uses the PostgreSQL initialization administrator.
Read-only `pg_roles` inspection reconfirmed **superuser, CREATEDB, CREATEROLE,
replication and BYPASSRLS**. Stage 15.2 confirmed ownership of all 19 tables.
No password or connection string was printed.

The actual `.env` ACL is inherited/unprotected. Broad inherited Allow entries
include Windows Users (`S-1-5-32-545`), ReadAndExecute, and Authenticated Users
(`S-1-5-11`), Modify. Git ignoring this file does not protect local access.
Restrict the file and review parent-directory permissions under separate owner
approval. No unauthorized access or compromise was demonstrated; no ACL was
changed here.

## Prepared runtime permissions

`runtime-grants.sql` grants explicit rights to NOLOGIN group
`asi_meal_runtime`; separate LOGIN `asi_meal_api` inherits it. Neither owns
objects or has administrative flags. The SQL accepts only `asi_meal_dev` or the
validator's `restore_<32 hex>` database and checks the group's safe role flags.

| Objects | Candidate rights |
| --- | --- |
| All 19 existing tables | SELECT, including schema revision for backup manifest |
| Users/sessions | INSERT; selected UPDATE columns for login/password change/user administration/session activity and revocation; DELETE sessions for bounded cleanup |
| Employees/imports/import rows | INSERT; approved employee/job UPDATE columns; import result rows append-only |
| Visitors/dishes | INSERT, supported UPDATE columns, DELETE unused records |
| Menus/dated assignments/offerings | INSERT; UPDATE assignment menu ID; restricted lock-support columns |
| Orders | INSERT; UPDATE receipt flag/metadata/version, no DELETE or historical-identity UPDATE |
| Order items | INSERT, UPDATE quantity, DELETE Pending lines; no snapshot-price UPDATE |
| Allocations | INSERT, UPDATE amount/update attribution, DELETE Pending replacements |
| Audit/receipt history | SELECT/INSERT only, no UPDATE/DELETE |
| Reference/category data | SELECT except category display-name UPDATE needed for locks; no price UPDATE |
| Sequences | USAGE on the 12 existing public sequences, no UPDATE/setval |
| Database/schema | CONNECT and public-schema USAGE; no CREATE/TEMP/TRUNCATE/TRIGGER/REFERENCES or ownership |

Required SELECT FOR SHARE/UPDATE statements need UPDATE on at least one column.
The implementation/trigger inspection identified locks in authorization,
imports, categories, menus, assignments and orders. Lock-only grants are
`menus.updated_at`, `menu_items.id`, `item_categories.display_name`; configured
and historical prices remain denied. Offering-ID UPDATE is a residual column
right; foreign keys protect referenced IDs. Removing it would require changing
the lock/schema design, outside scope. Trigger functions are invoker-rights;
normal DML worked after revoking PUBLIC EXECUTE on application functions.
Necessary pg_catalog calls, including advisory locks, use existing defaults.

The candidate revokes PUBLIC database/schema/object grants before explicit
rights. Inventory additional consumers before approval: other non-owner roles
would also lose those public rights. No broad future-object/default grants are
made; review grants explicitly after every migration. Current schema has no RLS
policies needing special backup behavior. Least privilege cannot replace app
authorization: a compromised runtime credential could still abuse allowed user
management or audit INSERT privileges.

Responsibilities:

- Runtime: proposed `asi_meal_api` -> `asi_meal_runtime`, without owner/admin membership.
- Migrations: controlled owner/DDL access kept outside API runtime. A dedicated
  NOLOGIN owner and maintenance-only migrator/ownership transfer need a separate
  tested plan; they were not silently created here.
- Administration: existing `asi_meal_dev` remains restricted initialization and
  recovery access. It is not demoted or rotated by this proposal. Docker
  operators remain effectively administrators.
- Backup: current helper privately exports a read-only snapshot through the
  verified API configuration; local-container administrator `pg_dump` imports it.
  It now recognizes the exact proposed username and reviewed Compose override
  pair. Runtime can read every manifest table and export snapshots; the admin
  dump remains separate. A dedicated backup identity is optional future work.

## Disposable evidence

```powershell
cd C:\asi-meal-management
.\.venv\Scripts\python.exe infra/dev/validate_runtime.py `
  --backup backups/asi-meal-dev-20261027T053346Z-bf583cc1/database.dump
```

This reuses the existing backup integrity/isolation/restore code. Before adding
fixtures it compared all 19 table counts/full-content fingerprints, totals,
revision and 12 ID sequences. Only then did it create isolated roles and a new
synthetic Super Admin authentication fixture. Random passwords exist in memory
and temporary container environment, never files/arguments/logs.

A new API worker shares only the restore container's `network none` namespace,
with source/tooling mounted read-only. It cannot reach the live database network.
Normal FastAPI TestClient requests exercise real password-authenticated TCP
connections, CSRF, stored-actor authorization and existing business services.
This is HTTP/SQL integration, not live browser acceptance.

Passed under `current_user=asi_meal_api`, all administrative flags false and no
owned tables:

- Reads of all manifest tables and read-only snapshot export.
- Normal login/session/logout; forced first password change; user create/update/
  disable and session revocation; session cleanup.
- Synthetic CSV employee insert/update with a leading-zero text ID.
- Dish/visitor creation, visitor rename, unused dish/visitor deletion.
- Menu with automatic rice; date lookup and assignment without replacing existing dates.
- Five-method employee split; Pending quantity and line remove/add edits;
  request-key retry; receipt/stale-version 409/reversal/re-receipt; historical
  customer snapshot preserved after employee rename.
- Visitor automatic Finance-only receipt, report/export bundle and Activity API.
- Synthetic Received sales/allocations **240.00**, SD **30.00**, exactly reconciled.

All **17** negative SQL probes returned insufficient privilege (42501): permanent
and temporary table/schema/role creation, trigger disable, table drop/truncate,
employee DELETE, audit UPDATE, receipt DELETE, category/recorded price UPDATE,
order identity UPDATE, revision UPDATE, sequence reset, owner-role escalation
and server-file read.

After grants/workflows, an administrator dump was readable and fully restored
from memory into another verified empty instance. All post-test table contents,
financial totals, leading-zero employee and safe sequence states matched.
Disposable databases used tmpfs, not persistent volumes. Exact temporary IDs
were removed; final inventory found no probe/restore containers. No shared
volume was deleted. An initial nested-restore attempt hit Python
`UnsupportedOperation` for BytesIO subprocess stdin; binary streaming was fixed
and the complete final drill passed.

## Exact live cutover proposal — separate approval required

Approve the PUBLIC-grant changes, secret ACL restriction, new runtime credential,
private configuration changes and brief API-only restart before executing.
Keep a local administrator terminal and rollback copy available. If either new
role already exists, stop and inspect; never overwrite an unknown role.

1. Verify Compose ownership, volume, DB identity and any other consumers. Create
   a new pre-cutover backup and restore validation:

   ```powershell
   cd C:\asi-meal-management
   .\.venv\Scripts\python.exe infra/dev/backup.py --restore-drill
   if ($LASTEXITCODE -ne 0) { throw 'No verified pre-cutover backup.' }
   cd infra\dev
   docker compose ps
   docker compose exec db psql -X -U asi_meal_dev -d asi_meal_dev `
     -c 'SELECT current_database(),current_user;'
   ```

2. After approval, create and verify the rollback copy **before** changing the
   active credential file or its ACL. Review the parent-folder ACL separately.
   The copy destination must be a new name in the fresh verified private backup
   directory; do not overwrite a prior rollback copy. Then restrict `.env` to
   the owner, SYSTEM, and the local Administrators group:

   ```powershell
   $ErrorActionPreference = 'Stop'
   $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
   $system = [System.Security.Principal.SecurityIdentifier]'S-1-5-18'
   $administrators = [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544'
   $accessSection = [System.Security.AccessControl.AccessControlSections]::Access
   $preCutover = Read-Host 'Full path of the new verified private backup directory'
   $folder = Get-Item -LiteralPath $preCutover
   $allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544')
   function Set-PrivateDacl([string]$path, [bool]$directory) {
     # AccessControlSections.Access deliberately avoids owner/group and SACL
     # handling; do not replace this with Set-Acl or SetOwner.
     $security = if ($directory) {
       [IO.Directory]::GetAccessControl($path, $accessSection)
     } else {
       [IO.File]::GetAccessControl($path, $accessSection)
     }
     $dacl = 'D:P' + ((@($sid, $system, $administrators) | ForEach-Object {
       "(A;;FA;;;$($_.Value))"
     }) -join '')
     $security.SetSecurityDescriptorSddlForm($dacl, $accessSection)
     if ($directory) { [IO.Directory]::SetAccessControl($path, $security) }
     else { [IO.File]::SetAccessControl($path, $security) }
   }
   function Assert-PrivateDacl([string]$path, [bool]$directory) {
     $security = if ($directory) {
       [IO.Directory]::GetAccessControl($path, $accessSection)
     } else {
       [IO.File]::GetAccessControl($path, $accessSection)
     }
     $actual = @($security.Access | ForEach-Object {
       $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
     } | Sort-Object -Unique)
     if (-not $security.AreAccessRulesProtected -or
         (Compare-Object -ReferenceObject ($allowed | Sort-Object) -DifferenceObject $actual)) {
       throw "Stop: DACL verification failed for $path."
     }
   }
   if (-not $folder.FullName.StartsWith('C:\asi-meal-management\backups\') -or
       ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
       -not (Test-Path -LiteralPath (Join-Path $folder.FullName 'verification.json'))) {
     throw 'Stop: backup destination is not a verified private project directory.'
   }
   $rollbackEnv = Join-Path $preCutover 'compose.env.before-cutover'
   if (Test-Path -LiteralPath $rollbackEnv) { throw 'Stop: rollback copy already exists.' }
   Copy-Item -LiteralPath .env -Destination $rollbackEnv -ErrorAction Stop
   if ((Get-FileHash -Algorithm SHA256 -LiteralPath .env).Hash -ne
       (Get-FileHash -Algorithm SHA256 -LiteralPath $rollbackEnv).Hash) {
     throw 'Stop: rollback configuration hash mismatch.'
   }
   [IO.File]::OpenRead($rollbackEnv).Dispose()
   # Preserve owner/group/audit policy and replace only DACLs. Confirm the
   # existing owners are approved separately before this point.
   Set-PrivateDacl $folder.FullName $true; Assert-PrivateDacl $folder.FullName $true
   Set-PrivateDacl $rollbackEnv $false; Assert-PrivateDacl $rollbackEnv $false
   Set-PrivateDacl (Get-Location).Path $true; Assert-PrivateDacl (Get-Location).Path $true
   Set-PrivateDacl (Join-Path (Get-Location).Path '.env') $false; Assert-PrivateDacl .env $false
   ```

3. Open normal interactive administrator psql, without secret arguments:

   ```powershell
   docker compose exec db psql -X -v ON_ERROR_STOP=1 -U asi_meal_dev -d asi_meal_dev
   ```

   After checking database identity, execute in that private session:

   ```sql
   BEGIN;
   CREATE ROLE asi_meal_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
   CREATE ROLE asi_meal_api LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
   GRANT asi_meal_runtime TO asi_meal_api;
   \password asi_meal_api
   COMMIT;
   \q
   ```

   Enter a strong URL-safe password at hidden prompts; never put it in SQL text,
   shell arguments/history or reports. No existing credential is rotated.

4. Apply the reviewed, transactional grant script to that exact database:

   ```powershell
   docker compose cp runtime-grants.sql db:/tmp/asi-runtime-grants.sql
   if ($LASTEXITCODE -ne 0) { throw 'Grant script copy failed.' }
   docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -U asi_meal_dev `
     -d asi_meal_dev -f /tmp/asi-runtime-grants.sql
   if ($LASTEXITCODE -ne 0) { throw 'Grants failed; do not restart API.' }
   ```

5. Using a private editor, add the matching `DEV_API_DB_PASSWORD` to the existing
   ignored `.env`; keep `DEV_DB_PASSWORD` unchanged. Do **not** set
   `COMPOSE_FILE` in `.env`. The approved runtime convention is explicit:
   every command that manages the restricted API uses both `-f compose.yaml`
   and `-f compose.runtime.yaml`, plus `--env-file .env`. Base-only emergency
   rollback commands use only `-f compose.yaml`. `compose.runtime.yaml` changes
   only API database identity and fails closed if the new secret is absent.

6. Validate without displaying resolved secrets, then recreate only API:

   ```powershell
   docker compose --env-file .env -f compose.yaml -f compose.runtime.yaml config --quiet
   if ($LASTEXITCODE -ne 0) { throw 'Invalid config; do not restart.' }
   docker compose --env-file .env -f compose.yaml -f compose.runtime.yaml config --services
   if ($LASTEXITCODE -ne 0) { throw 'Invalid service set; do not restart.' }
   docker compose --env-file .env -f compose.yaml -f compose.runtime.yaml up -d --no-deps api
   if ($LASTEXITCODE -ne 0) { throw 'API cutover failed; use rollback.' }
   docker compose --env-file .env -f compose.yaml -f compose.runtime.yaml ps
   ..\..\.venv\Scripts\python.exe verify.py
   ..\..\.venv\Scripts\python.exe verify.py --sign-in
   ..\..\.venv\Scripts\python.exe runtime_identity.py --post-cutover
   ```

   `runtime_identity.py` emits only database/user/role flags and public-table
   ownership; it never emits the URL or password and fails unless the API is
   actually connected as `asi_meal_api` with all dangerous flags false. Verify
   normal authorized sign-in and read-only employees/menus/reports/Activity;
   compare pre-cutover counts and run the backup/restore check again. Liveness
   200 alone is insufficient. Do not create live orders for privilege testing.
   Gateway/frontend/DB stay running; no build/migration is needed. API restart
   briefly interrupts requests; reconcile any in-flight order's request key and
   version before retrying.

Rollback uses the protected pre-cutover configuration and original API identity:

```powershell
cd C:\asi-meal-management\infra\dev
Copy-Item -LiteralPath (Join-Path $preCutover 'compose.env.before-cutover') -Destination .env -Force
if ((Get-FileHash -Algorithm SHA256 -LiteralPath .env).Hash -ne
    (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $preCutover 'compose.env.before-cutover')).Hash) {
  throw 'Rollback configuration hash mismatch.'
}
docker compose --env-file .env -f compose.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Rollback configuration invalid.' }
docker compose --env-file .env -f compose.yaml up -d --no-deps api
..\..\.venv\Scripts\python.exe verify.py
..\..\.venv\Scripts\python.exe verify.py --sign-in
```

Original admin credentials/access remain intact. No DB restore or business-data
rollback is required. Leave unused new roles for review rather than automatically
dropping them. Rollback restores the old overprivileged connection; record that
risk. Live cutover/rollback were prepared, not exercised in development.

## Backup protection and recovery readiness

Keep Stage 15.2's shared-snapshot logical dump, private ACL-protected directory,
SHA-256/content/financial checks and isolated restore. The helper now permits
only the exact base configuration or reviewed base+runtime pair; unrelated
Compose overrides remain refused. No second credential store was introduced.

Proposed policy, requiring owner approval: daily/before-maintenance backups;
seven daily/four weekly/three monthly verified copies; always retain the last
known-good pre-change backup. Store a second encrypted copy on a separate
approved on-premises device with restricted access; verify checksum and restore
after transfer. Dumps include HR data, password hashes and session material.
Storage encryption was not established by this stage.

Run isolated restores monthly and after schema/tool/PostgreSQL changes. A future
scheduler must alert a named operator on nonzero exit, stale/missing success
metadata, old backup age or low disk. No scheduler, notification integration,
deletion or transfer was enabled. Approve RPO/RTO and time a host-loss drill;
a daily-backup 24-hour RPO is a proposal, not a measured guarantee.

For failed frontend/API containers, verify ownership/effective Compose selection,
inspect `docker compose ps` and logs privately, then use
`docker compose up -d --no-deps frontend` or `... api` for the exact affected
service. After diagnosis, `docker compose restart <exact-service>` is an option.
Recover DB first if it is the actual cause. Do not repeatedly restart API to
mask a database outage.

For DB container failure, verify the existing named volume before
`docker compose up -d db`. Check recovery/identity before reconnecting services.
If the expected volume is missing, stop rather than substituting an empty DB.
For storage loss, use a separately protected copy, restore into a new independent
instance, and compare all contents/totals before an approved permanent cutover.
Restore private environment/TLS configuration separately; a DB dump is not a
cluster-role/secret/CA backup. Review restored-session revocation before reopening
access. Full host-recovery guidance remains in the Stage 15.2 document.

No development failure was injected. Never use `down -v`, volume deletion/prune,
reset, or restore/clean against the live database. Plain down preserves named
volumes but interrupts the whole application and is unnecessary for backup or
an API role cutover.

## Operational configuration findings

| Area | Observation / action |
| --- | --- |
| Restart/dependencies | All four `unless-stopped`; DB health -> API health -> frontend health -> gateway startup. Startup gating does not restart merely unhealthy containers. |
| Health | DB pg_isready; API liveness only; frontend checks root; gateway no Docker health check. Add reviewed readiness/monitoring before operational reliance. |
| Network | Gateway alone exposes 43873 on specific LAN IP/loopback; DB/API internal. Remote-client firewall reachability not newly tested. |
| TLS | Normal trusted TLS 1.3; IP SAN 192.168.45.145, Caddy Local Authority ECC Intermediate. Leaf valid 2026-10-26 23:57:13Z through 2026-10-27 11:57:13Z at inspection. Caddy manages short-lived internal leafs; renewal failure was not simulated. Preserve private TLS volume/CA; manage client root trust separately. |
| Secrets | Broad inherited `.env` ACL as above; Docker administrators can inspect env credentials. Database secrets are not deliberately browser settings. |
| Logs | All four json-file, empty rotation options; no explicit bounded rotation observed. Last 60-minute inspection had zero ERROR/FATAL/PANIC markers, not proof of error-free or privacy-safe logs. Uvicorn access logs may include search-query identifiers. Review sanitization/retention; propose bounded logs such as 10 MiB x 5 files/service in an approved recreation. |
| Capacity/resources | No explicit memory/CPU/PID limits. DB about 10.3 MB, backing filesystem about 856 GiB available/11% used; Windows drive about 1.37 TB free. No immediate shortage demonstrated. Docker Desktop VM limits not assessed. Monitor logs/dumps/WAL and size budgets from actual load. |
| Transient DB loss | Engine hides parameters but has no explicit pool_pre_ping/connect timeout. Stale connections may yield generic 503 before invalidation/recovery. No automatic financial-write replay; reconcile request keys after ambiguous failure. Controlled outage/readiness tests and connection hardening remain future work. |
| Reproducibility | Reload servers/source mounts and mostly unpinned Python requirements remain development choices; no dependency or production deployment change. |

## Ranked remaining risks

| Priority | Finding |
| --- | --- |
| P0 | None demonstrated; not general production certification. |
| P1 | Live runtime still superuser; candidate cutover awaits approval. |
| P1 | Actual secret-file ACL permits broad local read/modify; owner-approved file/parent ACL remediation needed. |
| P1 | No approved schedule/alerts/secondary backup copy, verified encryption or timed host-loss recovery/RPO/RTO. |
| P2 | Unbounded configured logging and potential query-string personal information. |
| P2 | Liveness-only checks, no transient-outage drill/monitoring or measured resource budgets. |
| P2 | Dedicated migration-owner and production reproducibility work remains. |

## Verification and files

- Relevant backend PostgreSQL tests: **155 passed**, 32.72 seconds, covering
  authentication, orders, protected HTTP and reporting. Existing migrations were
  used only by the disposable harness; no new/live migration.
- Final isolated runtime probe/full post-grant restore passed; 17 privilege
  denials and exact 240.00 sales/30.00 SD reconciliation.
- Backup unit tests: **4 passed**, including unrelated-override and corrupt-
  archive refusal. Python syntax, base/candidate Compose config and diff checks passed.
- Final HTTPS: app/health 200; unauthenticated protected endpoints 401; docs/debug
  404; untrusted-origin login 403. No normal live sign-in was attempted here.
- No frontend change, so frontend tests/lint/build were not rerun; no rebuild/restart.

New: `infra/dev/runtime-grants.sql`, `infra/dev/compose.runtime.yaml`,
`infra/dev/validate_runtime.py`, `infra/dev/runtime_probe.py`, this document.
Modified: `infra/dev/backup.py` (reuse, strict future-role/config compatibility,
in-memory isolated validation), `infra/dev/test_backup.py` (config boundary
coverage), `infra/dev/README.md` (guide link). Existing unrelated work preserved.

Stage 15.3 stops before live changes. Stage 15.4 has not started.
