"""Prevent reintroduction of the full-descriptor ACL path that needs SeSecurityPrivilege."""

from pathlib import Path
import unittest


SOURCE = Path(__file__).with_name("test_cutover_safeguards.ps1").read_text(encoding="utf-8")


class DaclOnlyAclProcedureTests(unittest.TestCase):
    def test_acl_replacement_is_dacl_only_and_preserves_owner(self):
        self.assertIn("AccessControlSections]::Access", SOURCE)
        self.assertIn("SetSecurityDescriptorSddlForm($dacl, $AccessSection)", SOURCE)
        self.assertIn("[IO.File]::SetAccessControl", SOURCE)
        self.assertIn("[IO.Directory]::SetAccessControl", SOURCE)
        self.assertNotIn("Set-PrivateAcl", SOURCE)
        self.assertNotIn("SetOwner(", SOURCE)

    def test_regression_exercises_the_sacl_privilege_failure_only_on_synthetic_directory(self):
        self.assertIn("Assert-SaclSetAclFails", SOURCE)
        self.assertIn("AddAuditRule", SOURCE)
        self.assertIn("PrivilegeNotHeldException", SOURCE)
        self.assertIn("legacy-sacl-descriptor", SOURCE)
        self.assertIn("SYNTHETIC_ONLY=placeholder", SOURCE)


if __name__ == "__main__":
    unittest.main()
