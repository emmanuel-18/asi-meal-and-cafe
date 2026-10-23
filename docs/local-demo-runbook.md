# Local synthetic demo runbook

This is a loopback-only development demo, not a production deployment. Use only
synthetic employee data. The root README also describes a separate persistent
Compose LAN setup; the authenticated loopback setup below and the current
[backend](../apps/api/DATABASE.md) and [frontend](../apps/web/README.md) documents
describe the implemented services. The existing Compose database volume is not
used for this demo.

## Tools

Use Windows PowerShell, Docker with the local `postgres:17` image, the project's
Python virtual environment and API dependencies in `apps/api/requirements.txt`,
and the existing frontend dependencies with Node.js 24 and npm. Check Docker,
`node --version`, and `.\.venv\Scripts\python.exe --version` from the project
root. If dependencies are missing, install the project's listed dependencies in
the intended isolated environment first; do not change system Node. The frontend
needs its existing `apps/web/node_modules` and lockfile dependencies.

## Persistent isolated Super Admin demo and backup

The Stage 14F.5B demo uses its own labeled PostgreSQL container and named
volume, separate from the Compose stack. Its Windows-user-protected metadata,
DPAPI-encrypted database password, and initial backup are under
`%LOCALAPPDATA%\ASI-Meal-Demos\demo-438864ebc209`. The DPAPI password can be
decrypted only by the Windows account that created it on this machine. Keep the
folder private and back up the credential securely as well as the database;
losing access to the Windows account can prevent password recovery. The backup
contains application data and must remain outside Git with restricted access.
Docker may assign a different loopback host port after a container restart.
Inspect the actual `5432/tcp` binding and update the demo connection settings
before restarting the API; do not rely on a previously recorded port.

To make a fresh backup, first verify the metadata, container label, volume and
database identity independently. Then use the demo container and database from
that metadata (never the Compose database):

```powershell
$demoFolder = Join-Path $env:LOCALAPPDATA 'ASI-Meal-Demos\demo-438864ebc209'
$demo = Get-Content -Raw (Join-Path $demoFolder 'demo.json') | ConvertFrom-Json
$info = (docker inspect $demo.container | ConvertFrom-Json)[0]
if ($info.Config.Labels.'asi.meal.demo' -ne $demo.id -or $info.Mounts[0].Name -ne $demo.volume) { throw 'Demo identity mismatch.' }
docker exec $demo.container psql -U $demo.user -d $demo.database -c 'SELECT current_database(), current_user;'
docker exec $demo.container pg_dump -Fc -U $demo.user -d $demo.database -f /tmp/asi-demo-backup.dump
if ($LASTEXITCODE -ne 0) { throw 'Backup failed.' }
docker exec $demo.container pg_restore -l /tmp/asi-demo-backup.dump | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Backup is unreadable.' }
docker cp ($demo.container + ':/tmp/asi-demo-backup.dump') (Join-Path $demoFolder 'asi-demo-backup.dump')
if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed.' }
```

Before recovery, create and independently verify a **new empty isolated**
PostgreSQL database and its target container; never restore over the Compose
database or an existing demo. Copy the protected archive into that new
container, inspect it with `pg_restore -l`, then restore with
`pg_restore --exit-on-error -U <target-user> -d <empty-target-database> <archive>`.
Verify the revision and data in the new target. A tested restore and a separate
backup of the required credentials are necessary before relying on recovery;
the initial backup's archive readability and copied-file hash were checked,
but a full restore has not yet been tested.

## Disposable database

In a PowerShell terminal at `C:\asi-meal-management`, create a fresh, uniquely
named PostgreSQL container. These variables and credentials are local to this
terminal and are not default application credentials. The container has temporary
storage and binds only a random loopback port; stopping it removes its data.

```powershell
$demoNonce = [guid]::NewGuid().ToString('N')
$demoName = "asi-meal-demo-$demoNonce"
$demoDb = "asi_demo_$demoNonce"
$demoUser = "demo_$demoNonce"
$env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$demoId = docker run --detach --rm --name $demoName --label "asi.meal.demo=$demoNonce" --label 'asi.meal.disposable=true' --tmpfs '/var/lib/postgresql/data:rw' --publish '127.0.0.1::5432' --env "POSTGRES_USER=$demoUser" --env "POSTGRES_DB=$demoDb" --env POSTGRES_PASSWORD postgres:17
if ($LASTEXITCODE -ne 0 -or -not $demoId) { throw 'Could not create demo container.' }
```

Before any database connection or migration, inspect the **exact ID** just
created. Stop if any check fails; do not substitute an existing container.

```powershell
$demoInfo = (docker inspect $demoId | ConvertFrom-Json)[0]
if ($demoInfo.Id -ne $demoId -or $demoInfo.Name -ne "/$demoName" -or $demoInfo.Config.Image -ne 'postgres:17' -or $demoInfo.Config.Labels.'asi.meal.demo' -ne $demoNonce -or $demoInfo.Config.Labels.'asi.meal.disposable' -ne 'true' -or $demoInfo.Config.Labels.'com.docker.compose.project' -or $demoInfo.HostConfig.Binds -or $demoInfo.HostConfig.Tmpfs.'/var/lib/postgresql/data' -ne 'rw' -or @($demoInfo.Mounts | Where-Object { $_.Type -ne 'tmpfs' -or $_.Destination -ne '/var/lib/postgresql/data' }).Count -ne 0) { throw 'Demo isolation verification failed.' }
$demoBinding = @($demoInfo.NetworkSettings.Ports.'5432/tcp')
if ($demoBinding.Count -ne 1 -or $demoBinding[0].HostIp -ne '127.0.0.1') { throw 'Demo port is not loopback-only.' }
$demoPort = $demoBinding[0].HostPort
```

Wait until `docker exec $demoId pg_isready -U $demoUser -d $demoDb` reports ready.
Then verify the database name and that the public schema has no tables using the
container's own `psql` before migration:

```powershell
docker exec $demoId psql -U $demoUser -d $demoDb -c 'SELECT current_database();'
docker exec $demoId psql -U $demoUser -d $demoDb -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public';"
```

The database must be `$demoDb` and the table list must be empty. If not, stop.
Keep the URL private and do not print it, put it in a file, or commit it:

```powershell
$env:ASI_DATABASE_URL = "postgresql+psycopg://${demoUser}:$($env:POSTGRES_PASSWORD)@127.0.0.1:${demoPort}/${demoDb}"
$env:PYTHONPATH = 'C:\asi-meal-management\apps\api\src'
Push-Location apps/api
..\..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
Pop-Location
```

Migrations are explicit and do not create accounts. The seed migration provides
the three starting category prices, not employees or orders.

## First Admin and servers

### Stage 14F.3 rollout and Super Admin promotion

Do not apply migrations or restart an existing demo until a separate rollout is
authorized. First verify the intended database and backup, and set its private
`ASI_DATABASE_URL` in your terminal; never print the URL. From the project root,
with `PYTHONPATH` set as above, apply the existing revisions explicitly:

```powershell
Push-Location apps/api
..\..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
Pop-Location
```

Then, only if the intended account is named `admin1`, invoke the interactive
promotion explicitly:

```powershell
.\.venv\Scripts\python.exe -m asi_meal_api.auth_cli promote-admin1
```

Compare the displayed database, server, user, target ID and name with the
intended demo. Enter your own local operator identifier and a nonsecret reason,
then type `PROMOTE admin1` only if every detail is correct. The operator identity
is a local self-attestation, not verified application identity. The command
preserves the password, revokes that user's sessions and audits the change;
repeating it makes no additional change. An absent, disabled or different
target is refused. For recovery of an existing active Super Admin, see the local
recovery procedure below.

### Local Super Admin recovery

This command assumes authorized local machine and database access; the operator
name is self-attested, not independently verified. It does not create or enable
accounts, change roles, or provide an HTTP recovery endpoint. Use it only after
independently verifying the target database and protecting a recent backup;
verify restoration in a separate isolated environment before production use.
Set `ASI_DATABASE_URL` privately to the verified target and `PYTHONPATH` as above,
then from the project root run:

```powershell
.\.venv\Scripts\python.exe -m asi_meal_api.auth_cli recover-super-admin
```

Enter the existing active Super Admin login. Compare the displayed database,
server, database user, account ID, name and role to the independently verified
target. Enter your operator identifier and a meaningful nonsecret reason (at
least 10 characters); type `RECOVER` followed by the displayed account ID only
if everything matches. Enter and confirm a unique temporary password through the
hidden prompts; do not put it in a command or logs. Communicate it privately to
the account owner. The account must change it on next login. Existing sessions
are revoked and the account update and self-attributed audit event commit together.
Loss of database/local administrator access or an inactive/missing Super Admin
is not resolved by this command; stop for a separately reviewed procedure.

After migrations and promotion, restart only the identified ASI Meal API and
frontend using their existing verified configuration and ports. The Users area
is available to Super Admin only. Create or reset an Admin/Assistant account
with a temporary password and communicate it privately through an approved
channel. The recipient signs in and changes it before using operational screens.
Role changes, disabling and password reset revoke existing sessions; a password
change revokes other sessions. Existing accounts do not require a change unless
explicitly reset. The read-only Activity Logs workspace is available to Super
Admin after the same separately authorized rollout. It shows only allowlisted
audit fields and the events that were actually recorded; it is not a complete
history of every action. Dates use Philippine time.

In the same terminal, with the verified demo URL still set, provision one
individual synthetic Admin interactively. The CLI requires a terminal and
hidden password entry; choose a unique password of at least 8 characters when
prompted. The maximum is 1,024 UTF-8 bytes; longer passwords are recommended for
production. It refuses
bootstrap if an Admin already exists.

```powershell
.\.venv\Scripts\python.exe -m asi_meal_api.auth_cli bootstrap-admin
```

Set the local development authentication profile and start the API in that
terminal. It listens only on loopback and does not run migrations at startup.

```powershell
$env:ASI_AUTH_ENABLED = 'true'
$env:ASI_AUTH_MODE = 'development'
$env:ASI_AUTH_ORIGINS = 'http://127.0.0.1:43871'
.\.venv\Scripts\python.exe -m uvicorn asi_meal_api.main:app --host 127.0.0.1 --port 43872 --no-proxy-headers
```

In a second terminal using Node 24, start Next.js from the project root:

```powershell
$env:ASI_API_ORIGIN = 'http://127.0.0.1:43872'
Set-Location C:\asi-meal-management\apps\web
npm run dev -- --hostname 127.0.0.1
```

Open `http://127.0.0.1:43871`. Use that exact origin throughout; `localhost`
is a different origin. These ports must be free, or choose free loopback ports
and adjust `ASI_AUTH_ORIGINS`, `ASI_API_ORIGIN`, and both server commands
consistently. Never disable Origin, CSRF or cookie checks.

## Synthetic data and walkthrough

Create a private local UTF-8 CSV containing exactly the ten headers below and
fictional rows only. Keep the first five approved fields in order and leave the
five ignored columns empty. For example, use employee number `SYN-0001` and
name `Synthetic Employee`; do not copy a real export. Import it from Employees
as the synthetic Admin, then search the directory. The complete contract is in
the [import specification](hrms-import-specification.md).

```csv
employee_number,full_name,position,campaign,line_of_business,assigned_site,email_address,primary_contact_number,alternative_contact_number,alternative_contact_number_2
SYN-0001,Synthetic Employee,Synthetic Position,Synthetic Campaign,Synthetic Business,,,,,
```

1. In Menu, create one synthetic dish in each category, create a menu, check its
   saved prices, and assign a chosen date. The seeded prices are ₱50, ₱75 and ₱15.
2. Create an employee order for one vegetable, two non-vegetable and three extra
   rice items. Split ₱245 into Cash ₱45 and GCash ₱200. Edit a Pending order,
   review its saved details, and mark it Received.
3. Create and reuse a synthetic visitor in order entry and record a Finance-only
   visitor order. Create a separate employee order with an SD allocation.
4. Check sales, allocations and SD in Reports. Reverse the SD order as Admin with
   a reason and confirmation; refresh and check its contribution disappears.
   Mark it Received again and refresh to check it returns once.
5. Sign out. The automated integration tests use separately controlled synthetic
   role fixtures to check Assistant Admin permissions. Do not change a real
   account merely to demonstrate this.

Stop the API and frontend that you started. To remove the temporary database,
use `docker stop $demoId` in the original terminal only after confirming that
`$demoId` is the verified ID created above. Its `--rm` container and tmpfs data
are removed; do not remove Compose volumes or other containers. Clear the
terminal's temporary credential variables when finished.

## Troubleshooting

- Docker unavailable or port binding fails: start Docker and use free loopback
  ports. Never fall back to an existing database or persistent volume.
- Migration fails: recheck the verified container, empty database, virtual
  environment, `PYTHONPATH`, and private `ASI_DATABASE_URL`; do not print the URL.
- Bootstrap fails: use an interactive terminal, check password confirmation and
  verify this is a fresh database with no existing Admin.
- Login or mutation fails: check exact origin, development mode, API availability
  and matching Next rewrite; the backend still enforces cookies and CSRF.
- Missing menu or unexpected prices: review the date assignment and saved menu;
  draft prices are references, and the server's saved prices are authoritative.
- An uncertain write outcome should be reviewed before a deliberate retry. No
  screen or test in this demo proves payment settlement or payroll completion.
