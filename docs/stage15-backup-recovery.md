# Stage 15.2 — Database protection, backup and recovery

Validated 2026-10-27, Singapore/Philippine time (UTC+8). Development only:
`https://192.168.45.145:43873/`. No workflow retesting or live business writes.

## Verified running target

| Component | Observed configuration |
| --- | --- |
| Compose | `asi-meal-dev`, `C:\asi-meal-management\infra\dev\compose.yaml` |
| Gateway | `asi-meal-dev-web-1`, ID prefix `f1193b6a7a37`, HTTPS 43873 on LAN IP and loopback |
| API | `asi-meal-dev-api-1`, ID prefix `357dcaa681da` |
| PostgreSQL | `asi-meal-dev-db-1`, ID prefix `1688902589ad`, PostgreSQL 17.11 |
| Database / runtime user | `asi_meal_dev` / `asi_meal_dev` |
| Data volume | `asi-meal-dev_dev_postgres`, mounted at `/var/lib/postgresql/data` |
| Database network | `asi-meal-dev_dev`, internal; no published PostgreSQL port |
| API connection verification | API container's actual `ASI_DATABASE_URL` parsed privately; a read-only connection confirmed database/user and server address `172.30.242.5`, matching the inspected database container |
| Schema revision | `0005_password_change_required` |

Container Compose labels identify the exact project, service and configuration
file. No obsolete standalone-demo database or other Compose project was used.
The URL/password were never printed or persisted in a new credential store.

The Compose file mounts a named volume, so container replacement and ordinary
`docker compose down` do not delete database data. This stage did **not** stop or
replace any development container to test persistence. The earlier cutover's
down/up comparison is recorded in `infra/dev/README.md`; current evidence is
read-only ownership/mount inspection and a fresh successful restore.

PostgreSQL's `pg_isready` health check runs every five seconds, timeout three
seconds, twelve retries. It proves connection acceptance, not financial integrity
or backup freshness. API `/health` is also liveness only. The fresh database
connection, snapshot scan and restore provide stronger database evidence here.

## Backup tool and daily commands

New development-only helper: `infra/dev/backup.py`. Requires Windows PowerShell,
Docker Desktop, the existing project Python, and the running verified API/DB.
It does not install packages or read the Windows DPAPI store.

From the project root:

```powershell
cd C:\asi-meal-management

# Create a consistent backup, check archive readability and source consistency.
.\.venv\Scripts\python.exe infra/dev/backup.py
if ($LASTEXITCODE -ne 0) { throw 'Backup failed or is unverified.' }

# Create a backup AND validate a full restore into a fresh disposable instance.
.\.venv\Scripts\python.exe infra/dev/backup.py --restore-drill
if ($LASTEXITCODE -ne 0) { throw 'Backup/restore validation failed.' }
```

Each invocation writes to a **new** timestamp/nonce directory under ignored
`C:\asi-meal-management\backups`. UTC filenames avoid time-zone ambiguity. It
never overwrites a backup, performs retention deletion, or schedules itself.

Before writing data, Windows ACL inheritance is disabled on the new directory.
Only the current Windows user and SYSTEM receive Full Control; files inherit
those rules. ACL protection was inspected on the actual directory and dump.
The dump contains employee/order information, password hashes and stored session
material. Keep it private; do not attach it to tickets, commit it or upload it.
ACLs are access controls, not encryption; encrypted host/backup storage remains
an operational requirement. Docker access itself confers administrative power.

The helper verifies source labels, exact Compose path, volume and absence of a
database host binding. It uses the API's existing configuration in memory to
connect and exports a REPEATABLE READ, READ ONLY PostgreSQL snapshot. Table
counts/content fingerprints and exact financial summaries use that snapshot;
`pg_dump -Fc --snapshot=...` uses the same snapshot while its transaction remains
open. There are no source INSERT/UPDATE/DELETE, migrations or sequence advances.
`pg_dump` takes normal read locks; a ten-second lock-wait limit fails rather
than waiting indefinitely for conflicting DDL. Fingerprint queries have a
60-second statement timeout; this is a small-development-database tool, not a
large-production backup performance certification.

Dump bytes are streamed directly to a binary file, avoiding PowerShell text
redirection corruption. The manifest `verification.json` records source identity,
tool version, archive size/SHA-256, all table counts/content fingerprints and
aggregate financial results. No raw employee rows, hashes or connection strings
are logged. Row fingerprints use sorted MD5 row hashes for non-adversarial
comparison, not cryptographic authenticity. SHA-256 detects archive changes;
trusted custody of the manifest is still required.

Failures return nonzero. A partial dump may remain in its private directory;
absence of a successful verification result means it must not be relied on.
The first guarded attempt stopped because PostgreSQL rendered an inet address
with `/32`; using PostgreSQL `host(inet_server_addr())` corrected comparison.
That attempt produced no dump and made no record changes.

## Actual backup and restore evidence

Representative final archive:

```text
C:\asi-meal-management\backups\asi-meal-dev-20261027T053346Z-bf583cc1\database.dump
```

- Created around **2026-10-27 13:33:47 UTC+8** (`05:33:47Z`).
- Size: **143,786 bytes**.
- SHA-256: `e40c782711c0ab18f1947e9e1a5e86603b3c06d2802343442f05e9c9044eaf29`.
- Server, `pg_dump` and `pg_restore`: **17.11 (Debian 17.11-1.pgdg13+2)**.
- `pg_restore --list` succeeded; a complete restore subsequently succeeded.
- Earlier successful archive in `asi-meal-dev-20261027T053221Z-41ee2c0a` is retained.
  No backup deletion was performed.

The restore used a new random database name, generated separate password kept
in process memory/container configuration, unique labeled container, no ports,
`--network none` and independent tmpfs PostgreSQL storage. **No persistent
restore volume was created**: tmpfs provides separate storage and avoids the
task's prohibition on volume deletion. This validates logical restoration, not
the durability of a new recovery volume. The exact local source image ID was
used for the main drill; subsequent existing-archive verification used the
locally installed `postgres:17` image with `--pull never`.

Only the newly returned container ID can receive a restore. Its name, nonce
label, lack of Compose ownership/binds/published ports, network isolation and
tmpfs mounts are checked first. `psql` confirms its random database name and
empty public schema. `pg_restore --single-transaction --exit-on-error
--no-owner --no-privileges` then restores over that empty database. It cannot
select the running development database as a restore target. Ownership/ACLs are
deliberately mapped to the isolated restore operator; production role/grant
restoration is a separate deployment task.

| Check | Source snapshot and restored result |
| --- | ---: |
| Tables compared | **19**, every row count and full-content fingerprint matched |
| Employees / users / visitors | **1,225 / 3 / 0** |
| Menus / date assignments / offerings | **4 / 3 / 11** |
| Orders | **8: 6 Received, 2 Pending** |
| Order items / allocations | **21 / 8** |
| Received item sales | **₱1,470.00** |
| Received payment allocations | **₱1,470.00** |
| Cash / Salary Deduction | **₱445.00 / ₱1,025.00** |
| GCash / Incentive / Finance | **₱0.00 / ₱0.00 / ₱0.00** |
| Unbalanced Received orders | **0** |
| Unvalidated public constraints | **0** |
| Restored ID sequences checked | **12**, next value would exceed existing IDs; no `nextval` called |

Employee numbers remain PostgreSQL `text`; employee records and historical
order snapshots match completely. There are **zero actual leading-zero
employee identifiers** in this backup, so real-record leading-zero restoration
cannot be demonstrated here. No synthetic employee was inserted to fill that
coverage gap. Received-only financial aggregation and all five payment totals
match; Pending amounts were excluded. No reporting calculations were modified.

After successful comparison, the helper reverified and removed only its exact
temporary container. Independent Docker inventory found no containers with the
restore label. No Docker volumes were deleted. All four original application
container IDs remained unchanged and healthy/Up.

## Reverify or restore a saved archive separately

Only run a trusted, privately held PostgreSQL archive; restoration executes the
archive's SQL. Keep `database.dump` and its original `verification.json` together.
The following checks hash/size before Docker operations and does **not** contact
the live API/database. It creates, validates and removes a new isolated restore
instance; it is not a permanent recovery cutover command.

```powershell
cd C:\asi-meal-management
$archive = 'C:\asi-meal-management\backups\asi-meal-dev-20261027T053346Z-bf583cc1\database.dump'
.\.venv\Scripts\python.exe infra/dev/backup.py --verify-backup $archive
if ($LASTEXITCODE -ne 0) { throw 'Saved backup verification failed.' }
```

This exact saved-archive path passed a second independent restore after the
final helper changes. It compared all 19 tables, financial totals and 12 ID
sequences. A nonzero exit means stop; do not redirect a restore to an existing
database or substitute the running database container. If isolation verification
fails, the unknown container is deliberately left for independent inspection.

## Recovery procedures and persistence risks

**Container failure with intact host storage:** inspect the intended Compose
labels and `asi-meal-dev_dev_postgres` mount first. From `infra/dev`, run
`docker compose config --quiet`, then `docker compose up -d db`. Existing named
volume contents should be reused; PostgreSQL performs its normal crash recovery.
Inspect database health/logs and verify database identity before starting/reusing
the remaining services with `docker compose up -d`. If the expected volume is
missing or PostgreSQL cannot recover, stop; do not initialize an empty substitute
and claim recovery. Back up surviving storage before any repair. No simulated
container failure/restart was performed in this stage.

**Host/storage failure:** the database volume and backups on this same disk may
both be lost. Recover a protected copy from a separately approved on-premises
storage location. Restore the approved code/configuration and securely recover
the private `.env` and required TLS material separately; a database dump does
not contain Compose files, role passwords, Docker volumes or Caddy CA keys.
Verify archive hash and run the isolated restore procedure first. Provision a
new permanent PostgreSQL 17 instance with a new empty, independently identified
volume/database; apply the same checked restore and comparisons there before
any separately authorized API cutover. Preserve the old volume. Configure
runtime roles and credentials explicitly rather than expecting `pg_dump` to
restore cluster roles. Retest HTTPS trust, authentication, reports and accounts
before reopening access. Stored sessions exist in the dump; review session
revocation under an authorized recovery plan before publishing a restored app.
No permanent recovery target/cutover was created or attempted here.

Never use `docker compose down -v`, volume prune, reset scripts, `pg_restore
--clean` against an existing database, or delete `asi-meal-dev_dev_postgres`.
Plain `down` preserves named volumes, but it still interrupts service; routine
backup requires no down/up. Volume persistence is not a backup.

**Proposed retention, requiring owner policy approval:** one daily backup,
retain seven daily/four weekly/three monthly verified copies; backup before
maintenance and keep the last known-good pre-change copy. Keep at least one
encrypted, access-controlled copy on separate approved on-premises storage,
with checksum and restore verification after copying. Never delete the last
verified copy to meet a quota. Review retention against employee-data obligations
and disk capacity. No schedule, recurring job, external transfer or automatic
deletion was configured. A 24-hour RPO is a possible daily-backup target, not a
measured guarantee; owner-approved RPO/RTO and a timed permanent recovery drill
remain outstanding.

## Runtime database privileges

Read-only `pg_roles` inspection of the actual API database user confirmed:
**superuser, CREATEDB, CREATEROLE, replication and BYPASSRLS are all enabled**.
The same role owns all 19 public tables. This is substantially broader than
runtime requirements and can bypass ordinary database controls/audit protection.
No roles, grants, credentials or accounts changed in this stage.

| Responsibility | Recommended separation |
| --- | --- |
| API runtime | Dedicated non-owner LOGIN; CONNECT/USAGE and only required table/sequence/function permissions. No superuser, role/database creation, replication or RLS bypass. Validate application/audit-trigger behavior before adopting grants. |
| Migrations | Separately controlled owner/migration identity; DDL privileges available only during authorized maintenance. |
| Backup | Separately controlled read/snapshot/dump identity with verified complete table/sequence access; backups must not omit records because of RLS. The current local-container method uses the existing initialization identity. |
| Administration | Restricted operator access for role management, recovery and infrastructure operations, outside application runtime. Docker operators remain effectively privileged. |

Role separation needs its own tested rollout, private credential configuration
and rollback plan. It is an unresolved production gate, not silently remediated.

## Checks, files and limits

- Four focused offline tests passed: source ownership/volume/port refusal,
  isolated restore refusal, manifest prerequisites/exact SQL money, and corrupt
  archive refusal before any Docker operation.
- Python syntax compilation passed for both new tooling files.
- Main backup/restore and separate existing-archive restore passed.
- Compose configuration validation passed; `git diff --check` passed.
- Normal TLS verification after operations: `/` **200**, `/health` **200**,
  `/auth/me` and `/api/users` **401**, `/docs` and `/openapi.json` **404**,
  untrusted-origin login **403**. No sign-in or account mutation was performed.
- No frontend/backend application changes, so no application rebuild or full
  business suite rerun was needed. Stage 15.1's 274/105 test results remain prior
  evidence, not newly run tests. No Docker permission operation remained blocked.

Files: `infra/dev/backup.py`, `infra/dev/test_backup.py`, this document and a
backup-guide link in `infra/dev/README.md`. Existing unrelated Stage 15.1 changes
were preserved. Archives/manifests are local Git-ignored artifacts. No live
records, schema, accounts, services or volumes were changed; no restart,
migration, commit or push occurred. No other Docker stack was touched.

Remaining limits: overprivileged runtime identity; no approved backup schedule,
retention enforcement or separate-storage copy; no host-loss/permanent-volume
recovery drill or measured RTO; no actual leading-zero employee fixture in this
data; logical dumps are point-in-time snapshots without WAL/PITR. Backup success
here does not establish production readiness. Stage 15.2 ends here.
