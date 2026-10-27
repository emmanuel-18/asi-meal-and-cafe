"""Validate candidate grants ONLY in a fresh isolated restore of a trusted backup.

Never connects to the live DB, changes live roles, or restarts services.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import backup

sys.path.insert(0, str(backup.ROOT / "apps/api/src"))
from asi_meal_api.auth import Passwords


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def validate(cid, base, database):
    # base/cid/database are supplied only after backup.restore_drill verifies a
    # newly created empty target, restores it, and compares the original data.
    nonce = uuid4().hex
    backup.verify_restore(backup.inspect(cid), backup.inspect(cid)["Name"].removeprefix("/asi-restore-"))
    db_password = secrets.token_urlsafe(40)
    login_password = secrets.token_urlsafe(32)
    login = "synthetic-privilege-" + nonce
    encoded = Passwords().hash(login_password)
    setup = ("CREATE ROLE asi_meal_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;"
             "CREATE ROLE asi_meal_api LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD "
             + literal(db_password) + "; GRANT asi_meal_runtime TO asi_meal_api;"
             "INSERT INTO users(login_name,display_name,password_hash,role_code) VALUES ("
             + literal(login) + ",'Synthetic Privilege Super Admin'," + literal(encoded) + ",'super_admin');")
    backup.run(base, input=setup.encode())
    backup.run(base, input=Path(__file__).with_name("runtime-grants.sql").read_bytes())
    # This new worker shares the restore's network-none namespace. It can reach
    # that database on localhost but cannot reach the live internal network.
    env = {**os.environ, "ASI_PROBE_DATABASE": database, "ASI_PROBE_DB_PASSWORD": db_password,
           "ASI_PROBE_LOGIN": login, "ASI_PROBE_LOGIN_PASSWORD": login_password}
    args = ["docker", "run", "--rm", "--pull", "never", "--network", "container:" + cid,
            "--label", "asi.meal.runtime-probe=" + nonce,
            "--mount", f"type=bind,source={backup.ROOT / 'apps/api/src'},target=/app/src,readonly",
            "--mount", f"type=bind,source={Path(__file__).resolve().parent},target=/review,readonly"]
    for key in ("ASI_PROBE_DATABASE", "ASI_PROBE_DB_PASSWORD", "ASI_PROBE_LOGIN", "ASI_PROBE_LOGIN_PASSWORD"):
        args.extend(["--env", key])
    args.extend(["--entrypoint", "python", "asi-meal-dev-api", "/review/runtime_probe.py"])
    probe = subprocess.run(args, capture_output=True, env=env)
    if probe.returncode:
        # Worker emits only deliberate safe diagnostics; no tracebacks/SQL data.
        error = probe.stderr.decode(errors="replace").strip()
        if error.startswith("Isolated runtime probe failed:") and "\n" not in error:
            raise RuntimeError(error)
        raise RuntimeError("Isolated runtime worker failed; sensitive subprocess output suppressed")
    result = json.loads(probe.stdout)
    # Verify that an admin backup still works after runtime privilege separation.
    dump = backup.run(["docker", "exec", cid, "pg_dump", "-Fc", "--no-password", "-U", "restore_operator", "-d", database])
    toc = backup.run(["docker", "exec", "-i", cid, "pg_restore", "--list"], input=dump)
    if b"TABLE DATA" not in toc:
        raise RuntimeError("Post-grant admin backup validation failed")
    result["post_grant_backup_readable"] = True
    sql = backup.manifest_sql(json.loads(backup.run(base, input=b"SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public';")))
    expected = json.loads(backup.run(base, input=("SET timezone='UTC';" + sql + ";").encode()).decode().splitlines()[-1])
    # Fully restore this post-grant dump as well; no sensitive temp file.
    repeated = backup.restore_drill(dump, sql, expected, "postgres:17")
    result["post_grant_backup_restored"] = repeated["status"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    args = parser.parse_args()
    archive, report = backup.verified_archive(args.backup)
    result = backup.restore_drill(archive, backup.manifest_sql(report["source"]["tables"]),
                                  report["source"], "postgres:17", validate=validate)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Runtime validation stopped: " + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
