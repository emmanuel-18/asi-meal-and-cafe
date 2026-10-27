"""Explicit local development backup and optional isolated restore drill.

Never accepts a database URL or a restore target. No live SQL writes or restarts.
Run from Windows with the project's Python and Docker Desktop.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
PROJECT = "asi-meal-dev"
DATABASE = "asi_meal_dev"
VOLUME = "asi-meal-dev_dev_postgres"

# Runs in the existing API container, using its actual configuration, not a
# second credential store. Exceptions deliberately omit connection details.
SNAPSHOT_WORKER = r'''
import json, os, sys
import psycopg
from sqlalchemy.engine import make_url
try:
    url = make_url(os.environ['ASI_DATABASE_URL'])
    if not (url.drivername == 'postgresql+psycopg' and url.host == 'db'
            and url.database == 'asi_meal_dev' and url.username in {'asi_meal_dev', 'asi_meal_api'}
            and (url.port or 5432) == 5432):
        raise RuntimeError('Target mismatch')
    with psycopg.connect(host=url.host, port=url.port or 5432,
            dbname=url.database, user=url.username, password=url.password,
            connect_timeout=10, application_name='asi-stage15-backup') as conn:
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL timezone = 'UTC'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        identity = conn.execute('SELECT current_database(), current_user, host(inet_server_addr())').fetchone()
        if identity[0:2] != ('asi_meal_dev', url.username) or identity[2] != sys.argv[1]:
            raise RuntimeError('Server identity mismatch')
        snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        role = conn.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        owned = conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user").fetchone()[0]
        print(json.dumps(dict(database=identity[0], user=identity[1], server=identity[2],
            snapshot=snapshot, tables=tables, role_flags=dict(zip(
            ['superuser','create_database','create_role','replication','bypass_rls'],role)), owned_tables=owned)), flush=True)
        query = sys.stdin.readline()
        print(json.dumps(conn.execute(query).fetchone()[0]), flush=True)
        sys.stdin.readline()  # Keep the snapshot alive until pg_dump finishes.
        conn.rollback()
except Exception:
    print('Verified read-only API database snapshot failed.', file=sys.stderr)
    sys.exit(1)
'''


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        # Database stderr can contain employee values; do not echo it.
        raise RuntimeError(f"Command failed ({Path(args[0]).name} {args[1]}), exit {result.returncode}; no sensitive output displayed")
    return result.stdout


def inspect(container):
    return json.loads(run(["docker", "inspect", container]))[0]


def verify_live(info, service):
    labels = info["Config"].get("Labels", {})
    files = tuple(Path(p).resolve() for p in labels.get("com.docker.compose.project.config_files", "").split(","))
    base = (ROOT / "infra/dev/compose.yaml").resolve()
    runtime = (ROOT / "infra/dev/compose.runtime.yaml").resolve()
    if (labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != service
            or files not in {(base,), (base, runtime)}
            or not info["State"]["Running"]):
        raise RuntimeError("Development Compose identity mismatch")
    if service == "db":
        if (info["Config"]["Image"] != "postgres:17"
                or info["NetworkSettings"]["Ports"].get("5432/tcp")
                or [(m["Type"], m.get("Name"), m["Destination"]) for m in info["Mounts"]]
                != [("volume", VOLUME, "/var/lib/postgresql/data")]):
            raise RuntimeError("Development PostgreSQL persistence/binding mismatch")


def manifest_sql(tables):
    required = {"alembic_version", "employees", "orders", "order_items", "payment_allocations", "users", "audit_events"}
    if not required.issubset(tables):
        raise RuntimeError("Required application tables missing")
    parts = []
    for table in tables:
        identifier = '"' + table.replace('"', '""') + '"'
        literal = "'" + table.replace("'", "''") + "'"
        parts.append(f"SELECT {literal} AS name, jsonb_build_object('count',count(*),"
                     "'digest',md5(coalesce(string_agg(h,'' ORDER BY h),''))) AS value "
                     f"FROM (SELECT md5(row_to_json(t)::text) h FROM public.{identifier} t) s")
    return """SELECT jsonb_build_object(
      'tables',(SELECT jsonb_object_agg(name,value) FROM (%s) t),
      'revision',(SELECT jsonb_agg(version_num ORDER BY version_num) FROM alembic_version),
      'employee_number_type',(SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='employees' AND column_name='employee_number'),
      'leading_zero_employees',(SELECT count(*) FROM employees WHERE employee_number LIKE '0%%'),
      'received_orders',(SELECT count(*) FROM orders WHERE is_received),
      'pending_orders',(SELECT count(*) FROM orders WHERE NOT is_received),
      'received_sales',(SELECT coalesce(sum(i.line_total),0)::text FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.is_received),
      'received_allocations',(SELECT coalesce(sum(p.amount),0)::text FROM payment_allocations p JOIN orders o ON o.id=p.order_id WHERE o.is_received),
      'salary_deduction',(SELECT coalesce(sum(p.amount),0)::text FROM payment_allocations p JOIN orders o ON o.id=p.order_id WHERE o.is_received AND p.payment_category_code='sd'),
      'payment_totals',(SELECT jsonb_object_agg(code,amount) FROM (SELECT c.code, coalesce(sum(p.amount) FILTER (WHERE o.is_received),0)::text amount FROM payment_categories c LEFT JOIN payment_allocations p ON p.payment_category_code=c.code LEFT JOIN orders o ON o.id=p.order_id GROUP BY c.code) a),
      'unbalanced_received',(SELECT count(*) FROM orders o WHERE is_received AND coalesce((SELECT sum(line_total) FROM order_items WHERE order_id=o.id),0) <> coalesce((SELECT sum(amount) FROM payment_allocations WHERE order_id=o.id),0)),
      'invalid_constraints',(SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated)
    )""" % " UNION ALL ".join(parts)


def protect_directory(folder):
    if os.name != "nt":
        raise RuntimeError("This development helper requires Windows ACL protection")
    if folder.exists():
        raise RuntimeError("Backup destination must be a new directory")
    # ACL is protected before any dump or manifest is written. Built-in SID use
    # avoids locale-dependent account names. No secrets are passed to PowerShell.
    code = r'''
$ErrorActionPreference = 'Stop'
$p = $env:ASI_BACKUP_DIRECTORY
New-Item -ItemType Directory -Path $p | Out-Null
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($sid)
foreach ($identity in @($sid, [System.Security.Principal.SecurityIdentifier]'S-1-5-18')) {
  $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
  $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $p -AclObject $acl
$check = Get-Acl -LiteralPath $p
if (-not $check.AreAccessRulesProtected -or $check.Access.Count -ne 2) { throw 'ACL verification failed' }
'''
    run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
        env={**os.environ, "ASI_BACKUP_DIRECTORY": str(folder)})


def verify_restore(info, nonce):
    if (info["Name"] != "/asi-restore-" + nonce
            or info["Config"]["Labels"].get("asi.meal.restore") != nonce
            or info["Config"]["Labels"].get("com.docker.compose.project")
            or info["HostConfig"].get("Binds")
            or info["HostConfig"]["NetworkMode"] != "none"
            or info["HostConfig"].get("PortBindings")
            or info["HostConfig"].get("Tmpfs") != {"/var/lib/postgresql/data": "rw"}
            or any(m["Type"] != "tmpfs" for m in info["Mounts"])):
        raise RuntimeError("Disposable restore isolation mismatch; container left for inspection")


def check_restored_sequences(base):
    # Read sequence state without nextval/setval. Sequence state is not MVCC;
    # compare it to restored IDs, not a separately timed live sequence reading.
    query = """SELECT format('SELECT json_build_object(''next'',CASE WHEN is_called THEN last_value + %s ELSE last_value END,''maximum'',(SELECT max(%I) FROM %I.%I)) FROM %I.%I;',
      s.seqincrement,a.attname,nt.nspname,t.relname,ns.nspname,q.relname)
      FROM pg_class q JOIN pg_namespace ns ON ns.oid=q.relnamespace
      JOIN pg_sequence s ON s.seqrelid=q.oid
      JOIN pg_depend d ON d.objid=q.oid AND d.deptype IN ('a','i')
      JOIN pg_class t ON t.oid=d.refobjid
      JOIN pg_namespace nt ON nt.oid=t.relnamespace
      JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
      WHERE ns.nspname='public' AND q.relkind='S' AND s.seqincrement > 0;"""
    statements = run(base, input=query.encode()).decode().splitlines()
    for statement in statements:
        state = json.loads(run(base, input=statement.encode()))
        if state["maximum"] is not None and state["next"] <= state["maximum"]:
            raise RuntimeError("Restored sequence could reuse an existing ID")
    return len(statements)


def restore_drill(archive, sql, expected, image, *, validate=None):
    nonce = uuid.uuid4().hex
    db = "restore_" + nonce
    username = "restore_operator"
    cid = run(["docker", "run", "--pull", "never", "--detach", "--network", "none", "--name", "asi-restore-" + nonce,
               "--label", "asi.meal.restore=" + nonce, "--tmpfs", "/var/lib/postgresql/data:rw",
               "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=" + username,
               "--env", "POSTGRES_DB=" + db, image],
              env={**os.environ, "POSTGRES_PASSWORD": secrets.token_urlsafe(40)}).decode().strip()
    verified = False
    try:
        verify_restore(inspect(cid), nonce)
        verified = True
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", cid, "pg_isready", "-h", "127.0.0.1", "-U", username, "-d", db], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL not ready")
        base = ["docker", "exec", "-i", cid, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", username, "-d", db]
        identity = run(base, input=b"SELECT current_database(); SELECT count(*) FROM pg_tables WHERE schemaname='public';").decode().splitlines()
        if identity != [db, "0"]:
            raise RuntimeError("Restore target is not the new empty database")
        restore = ["docker", "exec", "-i", cid, "pg_restore", "--exit-on-error", "--single-transaction",
                   "--no-owner", "--no-privileges", "-U", username, "-d", db]
        if isinstance(archive, bytes):
            run(restore, input=archive)
        else:
            with archive.open("rb") as stream:
                run(restore, stdin=stream)
        actual = json.loads(run(base, input=("SET timezone='UTC';\n" + sql + ";\n").encode()).decode().splitlines()[-1])
        if actual != expected:
            raise RuntimeError("Restore comparison failed; backup retained, no live changes")
        sequence_count = check_restored_sequences(base)
        validation = validate(cid, base, db) if validate is not None else None
        return {"status": "passed", "container": cid, "database": db,
                "storage": "isolated tmpfs, no persistent volumes", "sequences_safe": sequence_count,
                **({"validation": validation} if validation is not None else {}),
                "comparison": "all table counts/digests and financial summary identical"}
    finally:
        if verified:
            verify_restore(inspect(cid), nonce)
            run(["docker", "rm", "--force", cid])


def verified_archive(path):
    archive = path.resolve()
    report = json.loads(archive.with_name("verification.json").read_text(encoding="utf-8"))
    with archive.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual_hash != report["sha256"] or archive.stat().st_size != report["bytes"]:
        raise RuntimeError("Archive integrity mismatch; no restore started")
    return archive, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--restore-drill", action="store_true")
    mode.add_argument("--verify-backup", type=Path, help="Restore a trusted existing archive into a new disposable instance; no live connection")
    args = parser.parse_args()
    if args.verify_backup:
        archive, report = verified_archive(args.verify_backup)
        result = restore_drill(archive, manifest_sql(report["source"]["tables"]), report["source"], "postgres:17")
        print(json.dumps(result, indent=2))
        return
    db = inspect("asi-meal-dev-db-1")
    api = inspect("asi-meal-dev-api-1")
    verify_live(db, "db")
    verify_live(api, "api")
    ip = db["NetworkSettings"]["Networks"]["asi-meal-dev_dev"]["IPAddress"]
    folder = ROOT / "backups" / ("asi-meal-dev-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    if not folder.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("Backup directory resolves outside the project")
    protect_directory(folder)
    archive = folder / "database.dump"
    worker = subprocess.Popen(["docker", "exec", "-i", api["Id"], "python", "-u", "-c", SNAPSHOT_WORKER, ip],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = worker.stdout.readline()
        if not line:
            raise RuntimeError("Verified API snapshot unavailable; credentials were not displayed")
        identity = json.loads(line)
        sql = manifest_sql(identity.pop("tables"))
        worker.stdin.write(sql.replace("\n", " ") + "\n")
        worker.stdin.flush()
        source = json.loads(worker.stdout.readline())
        with archive.open("xb") as stream:
            result = subprocess.run(["docker", "exec", db["Id"], "pg_dump", "-Fc", "--no-password",
                                     "--lock-wait-timeout=10s", "--snapshot=" + identity["snapshot"],
                                     "-U", DATABASE, "-d", DATABASE], stdout=stream, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError("pg_dump failed; partial file retained, not a verified backup")
    finally:
        worker.communicate("done\n", timeout=30)
    if worker.returncode:
        raise RuntimeError("Snapshot worker failed; backup is unverified")
    with archive.open("rb") as stream:
        toc = run(["docker", "exec", "-i", db["Id"], "pg_restore", "--list"], stdin=stream)
    if b"TABLE DATA" not in toc:
        raise RuntimeError("Archive has no application table data")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    from decimal import Decimal
    if (source["unbalanced_received"] or source["invalid_constraints"]
            or Decimal(source["received_sales"]) != Decimal(source["received_allocations"])):
        raise RuntimeError("Source consistency check failed; backup retained, no restore attempted")
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), archive=str(archive),
                  bytes=archive.stat().st_size, sha256=digest, identity=identity, source=source,
                  tools=run(["docker", "exec", db["Id"], "pg_dump", "--version"]).decode().strip(),
                  live_container=db["Id"], volume=VOLUME, archive_readable=True)
    (folder / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.restore_drill:
        report["restore"] = restore_drill(archive, sql, source, db["Image"])
        (folder / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print arbitrary DB/driver/subprocess exception messages.
        print("Backup/restore validation stopped: " + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
