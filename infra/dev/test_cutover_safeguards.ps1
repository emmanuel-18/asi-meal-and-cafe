# Synthetic-only ACL and rollback-copy test for Stage 15.3B.1.
# It never reads, changes, or copies infra/dev/.env.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$AccessSection = [System.Security.AccessControl.AccessControlSections]::Access
$OwnerSection = [System.Security.AccessControl.AccessControlSections]::Owner

function Get-AllowedSids {
    $owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    return @($owner, [System.Security.Principal.SecurityIdentifier]'S-1-5-18',
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544')
}

function Get-OwnerSid([string]$Path, [bool]$Directory) {
    $security = if ($Directory) {
        [IO.Directory]::GetAccessControl($Path, $OwnerSection)
    } else {
        [IO.File]::GetAccessControl($Path, $OwnerSection)
    }
    return $security.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
}

function Set-PrivateDacl([string]$Path, [bool]$Directory) {
    # Deliberately request and replace only the DACL. Do not set owner/group or
    # read/write audit/SACL data, so SeSecurityPrivilege is not required.
    $security = if ($Directory) {
        [IO.Directory]::GetAccessControl($Path, $AccessSection)
    } else {
        [IO.File]::GetAccessControl($Path, $AccessSection)
    }
    $dacl = 'D:P' + ((Get-AllowedSids | ForEach-Object { "(A;;FA;;;$($_.Value))" }) -join '')
    $security.SetSecurityDescriptorSddlForm($dacl, $AccessSection)
    if ($Directory) {
        [IO.Directory]::SetAccessControl($Path, $security)
    } else {
        [IO.File]::SetAccessControl($Path, $security)
    }
}

function Assert-PrivateDacl([string]$Path, [bool]$Directory, [string]$ExpectedOwner) {
    $security = if ($Directory) {
        [IO.Directory]::GetAccessControl($Path, $AccessSection)
    } else {
        [IO.File]::GetAccessControl($Path, $AccessSection)
    }
    $allowed = @(Get-AllowedSids | ForEach-Object Value | Sort-Object -Unique)
    $rules = @($security.Access)
    $actual = @($rules | ForEach-Object {
        $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    } | Sort-Object -Unique)
    if (-not $security.AreAccessRulesProtected -or
        (Compare-Object -ReferenceObject $allowed -DifferenceObject $actual) -or
        @($rules | Where-Object { ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne [System.Security.AccessControl.FileSystemRights]::FullControl }).Count -ne 0 -or
        (Get-OwnerSid $Path $Directory) -ne $ExpectedOwner) {
        throw 'Private DACL/ownership verification failed.'
    }
}

function Assert-SaclSetAclFails([string]$Path) {
    # Regression test: a full-descriptor Set-Acl carrying audit/SACL state is
    # denied under this operator. The corrected DACL-only path must not do this.
    $legacy = New-Object System.Security.AccessControl.DirectorySecurity
    $legacy.SetAccessRuleProtection($true, $false)
    foreach ($sid in Get-AllowedSids) {
        $legacy.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    $legacy.AddAuditRule((New-Object System.Security.AccessControl.FileSystemAuditRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().User, 'ReadData',
        'None', 'None', 'Success')))
    try {
        Set-Acl -LiteralPath $Path -AclObject $legacy -ErrorAction Stop
    } catch [System.Security.AccessControl.PrivilegeNotHeldException] {
        return
    }
    throw 'SACL-bearing Set-Acl unexpectedly did not raise PrivilegeNotHeldException.'
}

$root = Join-Path ([IO.Path]::GetTempPath()) ('asi-cutover-safeguard-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Path $root | Out-Null
    $legacy = Join-Path $root 'legacy-sacl-descriptor'
    New-Item -ItemType Directory -Path $legacy | Out-Null
    Assert-SaclSetAclFails $legacy

    $source = Join-Path $root 'synthetic.env'
    Set-Content -LiteralPath $source -Value 'SYNTHETIC_ONLY=placeholder' -NoNewline
    $sourceOwner = Get-OwnerSid $source $false
    Set-PrivateDacl $source $false
    Assert-PrivateDacl $source $false $sourceOwner

    $backup = Join-Path $root 'rollback'
    New-Item -ItemType Directory -Path $backup | Out-Null
    $backupOwner = Get-OwnerSid $backup $true
    Set-PrivateDacl $backup $true
    Assert-PrivateDacl $backup $true $backupOwner
    $copy = Join-Path $backup 'compose.env.before-cutover'
    if (Test-Path -LiteralPath $copy) { throw 'Rollback destination already exists.' }
    Copy-Item -LiteralPath $source -Destination $copy -ErrorAction Stop
    $copyOwner = Get-OwnerSid $copy $false
    Set-PrivateDacl $copy $false
    Assert-PrivateDacl $copy $false $copyOwner
    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    $copyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $copy).Hash
    if ($sourceHash -ne $copyHash) { throw 'Rollback backup hash mismatch.' }
    [IO.File]::OpenRead($copy).Dispose()

    $restore = Join-Path $root 'synthetic-restored.env'
    Copy-Item -LiteralPath $copy -Destination $restore -ErrorAction Stop
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $restore).Hash -ne $copyHash) {
        throw 'Synthetic rollback restore hash mismatch.'
    }
    Write-Output 'Synthetic DACL-only ACL, rollback backup, and restore verification passed.'
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
