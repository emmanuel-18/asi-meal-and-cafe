# Stage 15.3B.1 — Windows ACL permission-blocker remediation

**Date:** 2026-10-27 (UTC+8)  
**Scope:** synthetic ACL validation and documentation correction only. The live
`.env`, parent directory, credentials, Docker services, PostgreSQL roles/grants,
and database were not changed.

## Root cause

The blocked Stage 15.3B procedure constructed a new `FileSecurity`/
`DirectorySecurity` object, called `SetOwner`, then submitted it with the
generic PowerShell `Set-Acl` cmdlet. That is a full security-descriptor write,
not a DACL-only update. On the target backup directory, Windows requested
`SeSecurityPrivilege`; that privilege protects SACL/audit security-descriptor
handling and is not held by the intended operator token.

The intended operation never needed to change owner, group, or audit/SACL
policy. Requesting a broad descriptor update was therefore unnecessary and
caused the mandatory stop.

## Corrected method

The revised procedure uses .NET file APIs with
`AccessControlSections.Access` only:

1. Read only the DACL from the file/directory.
2. Replace it with a protected DACL granting Full Control solely to the current
   operator SID, `SYSTEM` (`S-1-5-18`), and local `Administrators`
   (`S-1-5-32-544`).
3. Write the DACL through `File.SetAccessControl` or
   `Directory.SetAccessControl`.
4. Re-read only the DACL and verify inheritance is disabled and the identity
   allow-list is exact.
5. Independently check that owner remains unchanged; the corrected procedure
   never calls `SetOwner` and never reads/writes a SACL.

The actual approved command sequence was updated in
[`stage15-operational-readiness.md`](stage15-operational-readiness.md). It still
copies and SHA-256-verifies the rollback `.env` before changing any active ACL.
It now applies the same DACL-only protection to the backup directory, rollback
copy, `infra/dev` directory, and active `.env` during a separately authorized
cutover.

## Synthetic regression evidence

`infra/dev/test_cutover_safeguards.ps1` uses only a GUID-named temporary
directory and `SYNTHETIC_ONLY=placeholder` fixture. Under the intended operator
token it proves both sides of the regression:

- A synthetic `Set-Acl` operation carrying an explicit audit rule raises
  `PrivilegeNotHeldException`, demonstrating the SACL-sensitive failure class.
- The corrected DACL-only procedure succeeds without requesting
  `SeSecurityPrivilege`.
- The required current-owner/SYSTEM/Administrators entries remain, broad access
  is removed, and original ownership is preserved.
- The synthetic rollback copy is unique, hash-equal to its source, independently
  readable, DACL-protected, and restores with the same SHA-256 hash.

The focused Python regression test additionally rejects reintroduction of
`SetOwner` or the previous broad helper and asserts that the PowerShell script
contains the DACL-only access-section APIs and synthetic SACL-failure probe.

## Commands and results

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\dev\test_cutover_safeguards.ps1
.\.venv\Scripts\python.exe -m unittest infra\dev\test_acl_procedure.py
.\.venv\Scripts\python.exe -m py_compile infra\dev\runtime_identity.py infra\dev\validate_compose_runtime.py
git diff --check
```

The synthetic PowerShell test passed with:

```text
Synthetic DACL-only ACL, rollback backup, and restore verification passed.
```

## Remaining Stage 15.3B gates

The ACL blocker is corrected for the intended operator privilege level.
Stage 15.3B may be retried only with a new preflight and fresh backup/restore
drill. The live retry must still verify, before any write:

- exact Compose/service/volume/database identity;
- approved unchanged ownership for `infra/dev`, `.env`, and the new backup
  directory (the DACL-only procedure intentionally preserves owner);
- DACL-only verification after each protection step;
- no additional PostgreSQL consumer requiring legacy PUBLIC permissions;
- explicit base/runtime Compose resolution, then post-restart runtime identity.

No special user right, administrator elevation, or Windows audit-policy change
is required for the corrected DACL-only procedure. If the real target refuses a
DACL-only write, stop and report its error; do not grant `SeSecurityPrivilege`,
weaken the ACL, or substitute a broad-access workaround.

## Files changed

- `infra/dev/test_cutover_safeguards.ps1`
- `infra/dev/test_acl_procedure.py`
- `docs/stage15-operational-readiness.md`
- this document

No live cutover was attempted.
