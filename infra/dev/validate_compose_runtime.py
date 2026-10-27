"""Offline candidate-Compose contract validation with synthetic credentials.

It runs only ``docker compose config``.  It never starts, recreates, inspects,
or contacts containers or databases; synthetic values are held in a temporary
env file and neither the resolved config nor any password is printed.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from sqlalchemy.engine import make_url


HERE = Path(__file__).resolve().parent
EXPECTED_SERVICES = {"web", "frontend", "api", "db"}


def config(env_file: Path, *, ordinary: bool) -> dict:
    environment = os.environ.copy()
    args = ["docker", "compose", "--env-file", str(env_file)]
    if ordinary:
        # This models the documented, explicit convention for daily commands.
        environment["COMPOSE_PATH_SEPARATOR"] = ";"
        environment["COMPOSE_FILE"] = "compose.yaml;compose.runtime.yaml"
    else:
        args.extend(["-f", "compose.yaml", "-f", "compose.runtime.yaml"])
    args.extend(["config", "--format", "json"])
    result = subprocess.run(args, cwd=HERE, env=environment, capture_output=True)
    if result.returncode:
        raise RuntimeError("Candidate Compose resolution failed; no service was changed.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("Candidate Compose did not return a JSON configuration.") from None


def base_config(env_file: Path) -> dict:
    result = subprocess.run(["docker", "compose", "--env-file", str(env_file), "-f", "compose.yaml",
                             "config", "--format", "json"], cwd=HERE, capture_output=True)
    if result.returncode:
        raise RuntimeError("Base Compose resolution failed; no service was changed.")
    return json.loads(result.stdout)


def validate(candidate: dict, base: dict) -> None:
    services = candidate.get("services", {})
    if set(services) != EXPECTED_SERVICES or set(base.get("services", {})) != EXPECTED_SERVICES:
        raise RuntimeError("Candidate Compose service set changed unexpectedly.")
    candidate_api = services["api"].copy()
    base_api = base["services"]["api"].copy()
    candidate_env = candidate_api.pop("environment", {}).copy()
    base_env = base_api.pop("environment", {}).copy()
    raw_url = candidate_env.pop("ASI_DATABASE_URL", None)
    base_env.pop("ASI_DATABASE_URL", None)
    if candidate_api != base_api or candidate_env != base_env:
        raise RuntimeError("Candidate override changes API configuration beyond its database identity.")
    if any(services[name] != base["services"][name] for name in EXPECTED_SERVICES - {"api"}):
        raise RuntimeError("Candidate override changes a non-API service.")
    if candidate.get("networks") != base.get("networks") or candidate.get("volumes") != base.get("volumes"):
        raise RuntimeError("Candidate override changes networks or volumes.")
    url = make_url(raw_url or "")
    if not (url.drivername == "postgresql+psycopg" and url.username == "asi_meal_api"
            and url.host == "db" and (url.port or 5432) == 5432 and url.database == "asi_meal_dev"):
        raise RuntimeError("Candidate API URL does not use the restricted runtime identity.")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="asi-compose-contract-") as folder:
        env_file = Path(folder) / "synthetic.env"
        env_file.write_text("\n".join((
            "DEV_HOST=192.168.45.145", "DEV_WEB_PORT=43873",
            "DEV_DB_PASSWORD=synthetic-base-password",
            "DEV_API_DB_PASSWORD=synthetic-runtime-password",
        )), encoding="utf-8")
        base = base_config(env_file)
        explicit = config(env_file, ordinary=False)
        ordinary = config(env_file, ordinary=True)
        validate(explicit, base)
        validate(ordinary, base)
        if explicit != ordinary:
            raise RuntimeError("Explicit and ordinary runtime Compose configurations differ.")
    print("Candidate Compose contract passed with synthetic credentials; no service was changed.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
