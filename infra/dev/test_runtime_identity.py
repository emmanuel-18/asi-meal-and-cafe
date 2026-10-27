"""Offline unit tests for the redacted runtime-identity contract."""

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("runtime_identity", Path(__file__).with_name("runtime_identity.py"))
runtime_identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_identity)


def record(**changes):
    value = {
        "database": "asi_meal_dev", "user": "asi_meal_api", "superuser": False,
        "create_database": False, "create_role": False, "replication": False,
        "bypass_rls": False, "owned_public_tables": 0,
    }
    value.update(changes)
    return value


class RuntimeIdentityTests(unittest.TestCase):
    def test_restricted_runtime_passes_without_connection_details(self):
        self.assertEqual(runtime_identity.evaluate_identity(record())["user"], "asi_meal_api")

    def test_disposable_restore_database_is_supported_only_when_explicit(self):
        self.assertEqual(runtime_identity.evaluate_identity(
            record(database="restore_0123456789abcdef0123456789abcdef"),
            expected_database="restore_0123456789abcdef0123456789abcdef")["database"],
            "restore_0123456789abcdef0123456789abcdef")

    def test_old_superuser_and_owned_tables_are_refused(self):
        for changed in ({"user": "asi_meal_dev", "superuser": True}, {"owned_public_tables": 1}):
            with self.assertRaisesRegex(RuntimeError, "not using"):
                runtime_identity.evaluate_identity(record(**changed))

    def test_unexpected_fields_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            runtime_identity.evaluate_identity({**record(), "password": "never-accepted"})


if __name__ == "__main__":
    unittest.main()
