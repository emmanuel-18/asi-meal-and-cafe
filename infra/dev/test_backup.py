"""Offline boundary tests: no Docker, credentials or application DB access."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("dev_backup", Path(__file__).with_name("backup.py"))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupBoundaries(unittest.TestCase):
    def test_corrupt_archive_stops_before_any_docker_operation(self):
        with (patch("sys.argv", ["backup.py", "--verify-backup", "database.dump"]),
              patch.object(Path, "read_text", return_value=json.dumps({"sha256": "wrong", "bytes": 3})),
              patch.object(Path, "open", return_value=io.BytesIO(b"bad")),
              patch.object(backup, "run") as docker,
              patch.object(backup, "restore_drill") as restore):
            with self.assertRaisesRegex(RuntimeError, "integrity mismatch"):
                backup.main()
            docker.assert_not_called()
            restore.assert_not_called()

    def test_live_target_requires_exact_project_config_and_volume(self):
        info = {"Config": {"Image": "postgres:17", "Labels": {
            "com.docker.compose.project": "asi-meal-dev", "com.docker.compose.service": "db",
            "com.docker.compose.project.config_files": str(backup.ROOT / "infra/dev/compose.yaml")}},
            "State": {"Running": True}, "NetworkSettings": {"Ports": {"5432/tcp": None}},
            "Mounts": [{"Type": "volume", "Name": backup.VOLUME, "Destination": "/var/lib/postgresql/data"}]}
        backup.verify_live(info, "db")
        proposed = copy.deepcopy(info)
        proposed["Config"]["Labels"]["com.docker.compose.project.config_files"] += "," + str(backup.ROOT / "infra/dev/compose.runtime.yaml")
        backup.verify_live(proposed, "db")
        for change in ("project", "volume", "port", "config"):
            wrong = copy.deepcopy(info)
            if change == "project":
                wrong["Config"]["Labels"]["com.docker.compose.project"] = "unrelated"
            elif change == "volume":
                wrong["Mounts"][0]["Name"] = "unrelated"
            elif change == "port":
                wrong["NetworkSettings"]["Ports"]["5432/tcp"] = [{"HostIp": "0.0.0.0"}]
            else:
                wrong["Config"]["Labels"]["com.docker.compose.project.config_files"] += "," + str(backup.ROOT / "unrelated.yaml")
            with self.assertRaises(RuntimeError):
                backup.verify_live(wrong, "db")

    def test_restore_refuses_persistent_or_connected_target(self):
        info = {"Name": "/asi-restore-test", "Config": {"Labels": {"asi.meal.restore": "test"}},
                "HostConfig": {"NetworkMode": "none", "Binds": None, "PortBindings": {},
                               "Tmpfs": {"/var/lib/postgresql/data": "rw"}},
                "Mounts": [{"Type": "tmpfs"}]}
        backup.verify_restore(info, "test")
        for change in ("volume", "network", "name", "compose"):
            wrong = copy.deepcopy(info)
            if change == "volume":
                wrong["Mounts"][0]["Type"] = "volume"
            elif change == "network":
                wrong["HostConfig"]["NetworkMode"] = "asi-meal-dev_dev"
            elif change == "name":
                wrong["Name"] = "/asi-meal-dev-db-1"
            else:
                wrong["Config"]["Labels"]["com.docker.compose.project"] = "asi-meal-dev"
            with self.assertRaises(RuntimeError):
                backup.verify_restore(wrong, "test")

    def test_manifest_requires_financial_tables_and_exact_money(self):
        with self.assertRaises(RuntimeError):
            backup.manifest_sql(["employees"])
        query = backup.manifest_sql(["alembic_version", "employees", "orders", "order_items",
                                     "payment_allocations", "users", "audit_events"])
        self.assertIn("p.payment_category_code='sd'", query)
        self.assertIn("sum(i.line_total)", query)
        self.assertIn("::text", query)
        self.assertIn("LIKE '0%'", query)
        self.assertNotIn("UPDATE ", query)
        self.assertNotIn("DELETE ", query)


if __name__ == "__main__":
    unittest.main()
