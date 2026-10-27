# Isolated LAN development

This directory always selects Compose project `asi-meal-dev`. It does not manage
the original standalone demo database. This separate project can use the
configured development HTTPS port only after it is confirmed unbound.
The owner-confirmed development endpoint is `https://192.168.45.145:43873/`;
this supersedes older port assignments and historical protected-port labels.
Confirm the gateway's Compose labels and volume ownership before a rebuild.
Docker Desktop and Compose are required; dependencies run in Node 24, Python 3.13
and PostgreSQL 17 containers.

## Configuration and daily use

Keep `.env` private (Git ignores it). Set `DEV_HOST` to this computer's current
private LAN IPv4 address, `DEV_WEB_PORT` to the dedicated HTTPS port, and
`DEV_DB_PASSWORD` to a unique URL-safe random secret.
Do not copy the protected deployment's settings. If the IP changes, update
`DEV_HOST` and recreate the development services with the command below.

```powershell
cd C:\asi-meal-management\infra\dev
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 web frontend api db
docker compose down
docker compose up -d
```

Open `https://<DEV_HOST>:<DEV_WEB_PORT>/` or
`https://localhost:<DEV_WEB_PORT>/`.
HTTPS is required by the existing secure session profile. Caddy terminates TLS,
Next.js proxies `/auth/*` and `/api/*` internally, and only the gateway publishes
a host port. The API and PostgreSQL have no host bindings. API docs/debug routes
are not proxied. Health: `https://<DEV_HOST>:<DEV_WEB_PORT>/health`.

Export the **development** public CA certificate after startup:

```powershell
docker compose cp web:/data/caddy/pki/authorities/local/root.crt ./dev-root-ca.crt
```

Verify and trust this development CA on each authorized test machine using its
normal certificate-management procedure before signing in. Do not bypass browser
certificate warnings or distribute the CA private key. `dev-root-ca.crt` is only
a public certificate; keep private TLS data in the Compose volume.

Verify HTTPS without changing the Windows trust store (uses the public CA file):

```powershell
..\..\.venv\Scripts\python.exe verify.py
# Optional: enter your existing development account password in the hidden prompt.
..\..\.venv\Scripts\python.exe verify.py --sign-in
```

The optional check signs in and signs out through the normal API; it never creates
an account, changes a password, or stores credentials. It uses only the
configured development HTTPS port.

Windows Firewall must allow the configured development HTTPS port only for authorized LAN addresses (or
LocalSubnet for a trusted test LAN). Check with the
administrator; this setup does not change firewall rules, router forwarding, or
public-network permissions. Containers bind the specific LAN IP plus loopback,
not every host interface. Do not expose the port through a router.

At initial verification Ethernet was classified **Public**. Do not assume remote
access works or change the entire network profile just for this application.
An administrator can authorize this narrowly scoped rule, including on that
profile, from an elevated PowerShell terminal on the host:

```powershell
$devLanIp = (Get-Content .env | Where-Object { $_ -like 'DEV_HOST=*' }).Substring(9)
$devPort = (Get-Content .env | Where-Object { $_ -like 'DEV_WEB_PORT=*' }).Substring(13)
New-NetFirewallRule -DisplayName 'ASI Meal dev HTTPS LAN only' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort $devPort `
  -LocalAddress $devLanIp -RemoteAddress LocalSubnet -Profile Any
```

Use individual authorized remote IP addresses instead of `LocalSubnet` where
required. This rule does not expose PostgreSQL or the API. Update its
local address if the computer's LAN address changes. Confirm from another device
after trusting the public development CA; host-only HTTP checks cannot prove
remote firewall reachability.

## Data and migrations

Current-stack backup commands, verified restore evidence, retention guidance and
recovery procedures are in [Stage 15.2 backup and recovery](../../docs/stage15-backup-recovery.md).
From the project root, run `.\.venv\Scripts\python.exe infra/dev/backup.py --restore-drill`
for an explicit private backup and isolated restore check; it does not restart
services or write business records. No recurring backup is configured.

The [Stage 15.3 operational review](../../docs/stage15-operational-readiness.md)
contains tested candidate runtime grants and an **inactive** `compose.runtime.yaml`
override. Do not apply it or change live roles/credentials until the owner
approves the documented cutover. Current daily commands still use the base file.

`asi-meal-dev_dev_postgres` persists across `down`, rebuilds and reboots. Never
use `down -v`, prune its volume, or run a reset. No migration runs automatically.
Accounts retain their existing passwords, roles and first-login requirements.
Existing HTTP loopback cookies do not transfer to HTTPS; sign in normally again.

The initial cutover must use a verified development-only `pg_dump -Fc` backup,
restored **once into an empty** `asi_meal_dev` database with `pg_restore
--no-owner --no-privileges --exit-on-error`. Compare every table's row count and
full-content digest, plus the Alembic revision, before switching the API. Preserve
the original database/container/volume as a recovery source. Do not restore over
a populated target or rerun the cutover automatically. Once cut over, the two
databases are independent; do not write to the original through old host servers.

Initial cutover (2026-10-26): the existing standalone demo was backed up to
`backups/asi-dev-cutover-20261026-093345.dump` (ignored), archive readability and
SHA-256 copy integrity were verified, and a restore into the empty development
volume succeeded. All 19 tables matched by row count and full-content digest;
all sequences matched. The restored data includes 1,225 employees, 3 accounts
and 7 orders. The existing revision `0005_password_change_required` was already
head; no upgrade was applied. A subsequent development-only `down`/`up` preserved
all 19 tables exactly. The original database and volume remain unchanged.

For a separately approved future schema upgrade, back up this database and then
run existing migrations explicitly:

```powershell
docker compose exec api python -m alembic -c alembic.ini current
docker compose exec api python -m alembic -c alembic.ini upgrade head
```

Source under `apps/web/src`, `apps/web/public`, `next.config.ts`, and
`apps/api/src` is mounted read-only into the containers for hot reload. The
frontend permits only the configured `DEV_HOST` as an additional Next.js
development origin, which allows LAN development assets and hot reload without
allowing arbitrary origins. Rebuild after dependency changes. Do not run a
second host frontend on the configured development HTTPS port.

If startup fails, use `docker compose ps` and individual service logs; do not run
commands in `infra/` as a fallback. A missing `.env` is an intentional fail-closed
error. For sign-in failures check HTTPS trust, the exact origin, API/database
health, and normal account status. Never disable Origin, CSRF, or cookie checks.
