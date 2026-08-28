param(
  [Parameter(Mandatory = $true)]
  [string]$Installer,
  [Parameter(Mandatory = $true)]
  [string]$ReportPath
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
  throw "UNTESTED — NO TARGET MACHINE: run-windows-release-smoke.ps1 requires Windows"
}

$InstallerPath = (Resolve-Path $Installer).Path
$Report = [System.IO.Path]::GetFullPath($ReportPath)
$ReportDirectory = [System.IO.Path]::GetDirectoryName($Report)
New-Item -ItemType Directory -Path $ReportDirectory -Force | Out-Null
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("mathtutor-win-rc-" + [guid]::NewGuid().ToString("N"))
$InstallRoot = Join-Path $Work "Install Path 中文"
$DataRoot = Join-Path $Work "User Data 保留"
$SecretReport = Join-Path $Work "secret-store.json"
New-Item -ItemType Directory -Path $InstallRoot, $DataRoot -Force | Out-Null
$DataSentinel = Join-Path $DataRoot "uninstall-must-preserve.txt"
[System.IO.File]::WriteAllText($DataSentinel, "non-secret release-test marker")

try {
  # electron-builder NSIS is per-user (perMachine=false). /D must be the final
  # argument and exercises both spaces and Unicode in the install path.
  $Install = Start-Process -FilePath $InstallerPath -ArgumentList @("/S", "/D=$InstallRoot") -Wait -PassThru
  if ($Install.ExitCode -ne 0) { throw "NSIS install failed: exit $($Install.ExitCode)" }

  $Executable = Join-Path $InstallRoot "MathTutor.exe"
  if (-not (Test-Path $Executable -PathType Leaf)) { throw "Installed executable missing: $Executable" }
  $Python = Join-Path $InstallRoot "resources\python-runtime\python.exe"
  $PythonApp = Join-Path $InstallRoot "resources\python-app"
  if (-not (Test-Path $Python -PathType Leaf)) { throw "Relocated Python missing: $Python" }

  $Signature = Get-AuthenticodeSignature -FilePath $InstallerPath
  if ($Signature.Status -eq "Valid") {
    $SignatureStatus = "PASS"
    $SignatureReason = "AUTHENTICODE_VALID"
  } elseif ($Signature.Status -eq "NotSigned") {
    $SignatureStatus = "UNTESTED"
    $SignatureReason = "MISSING_EXTERNAL_CREDENTIAL"
  } else {
    $SignatureStatus = "FAIL"
    $SignatureReason = "AUTHENTICODE_INVALID"
  }

  $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
  $IsAdministrator = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $NonAdminStatus = if ($IsAdministrator) { "UNTESTED" } else { "PASS" }
  $UnicodeUsernameStatus = if ($env:USERNAME -match "[^\x00-\x7F]") { "PASS" } else { "UNTESTED" }

  $PreviousPythonPath = $env:PYTHONPATH
  $env:PYTHONPATH = $PythonApp
  $env:PYTHONNOUSERSITE = "1"
  & $Python (Join-Path $PSScriptRoot "rc-secret-store-sentinel.py") `
    --expected-platform Windows --output $SecretReport
  $SecretExit = $LASTEXITCODE
  $env:PYTHONPATH = $PreviousPythonPath

  $env:MATHTUTOR_DATA_ROOT = $DataRoot
  & node (Join-Path $PSScriptRoot "rc-public-release-smoke.js") `
    --platform win32 --artifact $Executable --secret-report $SecretReport --output $Report
  $SharedExit = $LASTEXITCODE

  $Uninstaller = Get-ChildItem -Path $InstallRoot -Filter "Uninstall*.exe" -File | Select-Object -First 1
  if ($null -eq $Uninstaller) { throw "NSIS uninstaller missing" }
  $Uninstall = Start-Process -FilePath $Uninstaller.FullName -ArgumentList "/S" -Wait -PassThru
  $UninstallPass = $Uninstall.ExitCode -eq 0 -and (Test-Path $DataSentinel -PathType Leaf)

  $Document = Get-Content -Raw -Path $Report | ConvertFrom-Json
  $Document.platform_checks | Add-Member -NotePropertyName nsis_install -NotePropertyValue $(if ($Install.ExitCode -eq 0) { "PASS" } else { "FAIL" })
  $Document.platform_checks | Add-Member -NotePropertyName unicode_and_space_install_path -NotePropertyValue "PASS"
  $Document.platform_checks | Add-Member -NotePropertyName unicode_username -NotePropertyValue ([ordered]@{ status = $UnicodeUsernameStatus; reason_code = $(if ($UnicodeUsernameStatus -eq "PASS") { "TARGET_USERNAME_NON_ASCII" } else { "TARGET_USERNAME_ASCII" }) })
  $Document.platform_checks | Add-Member -NotePropertyName non_admin_install -NotePropertyValue ([ordered]@{ status = $NonAdminStatus; reason_code = $(if ($NonAdminStatus -eq "PASS") { "NON_ADMIN_TARGET_SESSION" } else { "TARGET_SESSION_IS_ADMIN" }) })
  $Document.platform_checks | Add-Member -NotePropertyName authenticode -NotePropertyValue ([ordered]@{ status = $SignatureStatus; reason_code = $SignatureReason })
  $Document.platform_checks | Add-Member -NotePropertyName secret_probe_exit_code -NotePropertyValue $SecretExit
  $Document.platform_checks | Add-Member -NotePropertyName uninstall_preserves_user_data -NotePropertyValue $(if ($UninstallPass) { "PASS" } else { "FAIL" })
  $Document.platform_checks | Add-Member -NotePropertyName installer_sha256 -NotePropertyValue ((Get-FileHash -Algorithm SHA256 $InstallerPath).Hash.ToLowerInvariant())
  if (-not $UninstallPass -or $SignatureStatus -eq "FAIL") { $Document.status = "FAIL" }
  $Document | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 -Path $Report

  if ($Document.status -eq "PASS") { exit 0 }
  if ($Document.status -eq "PARTIAL") { exit 2 }
  exit 1
} finally {
  # Harness cleanup is separate from the uninstall assertion above. The
  # assertion is evaluated before this isolated test directory is removed.
  if (Test-Path $Work) { Remove-Item -LiteralPath $Work -Recurse -Force }
}
