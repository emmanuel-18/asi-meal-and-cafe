"""Redacted, operator-only proof of the API's effective PostgreSQL identity.

This tool is intentionally not an HTTP endpoint.  It reads the API container's
already-configured connection string only inside that container, then emits a
small allow-listed identity record.  It never prints a URL, password, session,
or application row.  Run it only after a separately approved API cutover.
"""

import argparse
import json
import subprocess
import sys

from pathlib import Path


PROJECT = "asi-meal-dev"
API_CONTAINER = "asi-meal-dev-api-1"
EXPECTED = "asi_meal_api"

WORKER = r'''
import json, os, sys
import psycopg
from sqlalchemy.engine import make_url
try:
    url = make_url(os.environ["ASI_DATABASE_URL"])
    if not (url.drivername == "postgresql+psycopg" and url.host == "db"
            and url.database == "asi_meal_dev" and (url.port or 5432) == 5432):
        raise RuntimeError("API target does not match the approved development database")
    with psycopg.connect(host=url.host, port=url.port or 5432, dbname=url.database,
                         user=url.username, password=url.password, connect_timeout=10,
                         application_name="asi-runtime-identity") as conn:
        conn.execute("BEGIN READ ONLY")
        row = conn.execute("""
            SELECT current_database(), current_user, r.rolsuper, r.rolcreatedb,
                   r.rolcreaterole, r.rolreplication, r.rolbypassrls,
                   (SELECT count(*) FROM pg_tables
                    WHERE schemaname='public' AND tableowner=current_user)
            FROM pg_roles r WHERE r.rolname=current_user
        """).fetchone()
        if row is None:
            raise RuntimeError("Current database role is unavailable")
        print(json.dumps({"database": row[0], "user": row[1],
            "superuser": row[2], "create_database": row[3],
            "create_role": row[4], "replication": row[5],
            "bypass_rls": row[6], "owned_public_tables": row[7]}))
        conn.rollback()
except Exception:
    print("Runtime identity verification failed.", file=sys.stderr)
    sys.exit(1)
'''


def safe_run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise RuntimeError("Runtime identity verification failed.")
    return result.stdout


def api_identity_from_inspect(raw: bytes) -> str:
    """Reject unrelated/non-running Compose API containers without logging labels."""
    info = json.loads(raw)[0]
    labels = info["Config"].get("Labels", {})
    # The disposable probe imports this module from /review, which deliberately
    # has no project-root parents. Resolve the host project only for the
    # operator-facing Docker inspection path.
    root = Path(__file__).resolve().parents[2]
    base = (root / "infra/dev/compose.yaml").resolve()
    runtime = (root / "infra/dev/compose.runtime.yaml").resolve()
    files = tuple(Path(p).resolve() for p in labels.get(
        "com.docker.compose.project.config_files", "").split(","))
    if (labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "api"
            or files not in {(base,), (base, runtime)}
            or not info["State"]["Running"]):
        raise RuntimeError("Runtime identity verification refused an unverified API container.")
    return info["Id"]


def evaluate_identity(record: dict[str, object], *, expected_database: str = "asi_meal_dev") -> dict[str, object]:
    """Return only allowed evidence and fail closed unless the runtime is restricted."""
    required = {"database", "user", "superuser", "create_database", "create_role",
                "replication", "bypass_rls", "owned_public_tables"}
    if set(record) != required:
        raise RuntimeError("Runtime identity verification returned an unexpected record.")
    if (record["database"] != expected_database or record["user"] != EXPECTED
            or any(record[key] is not False for key in (
                "superuser", "create_database", "create_role", "replication", "bypass_rls"))
            or record["owned_public_tables"] != 0):
        raise RuntimeError("API is not using the approved restricted runtime role.")
    return {key: record[key] for key in (
        "database", "user", "superuser", "create_database", "create_role",
        "replication", "bypass_rls", "owned_public_tables")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-cutover", action="store_true",
                        help="required acknowledgement for a separately approved live check")
    args = parser.parse_args()
    if not args.post_cutover:
        raise RuntimeError("Refusing live verification without --post-cutover.")
    container_id = api_identity_from_inspect(safe_run(["docker", "inspect", API_CONTAINER]))
    raw = safe_run(["docker", "exec", container_id, "python", "-u", "-c", WORKER])
    try:
        record = json.loads(raw)
        print(json.dumps(evaluate_identity(record), sort_keys=True))
    except (json.JSONDecodeError, RuntimeError):
        raise RuntimeError("Runtime identity verification failed.") from None


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
