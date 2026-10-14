[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$OutputPath,
  [string]$BuildPython = "py",
  [string[]]$BuildPythonArgs = @("-3.12")
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
  throw "The Windows Python runtime must be assembled on Windows."
}

$PythonVersion = "3.12.10"
$ArchiveName = "python-$PythonVersion-embed-amd64.zip"
$ArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/$ArchiveName"
# SHA-256 from the python.org Sigstore bundle for the x64 embeddable package.
$ArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

$DesktopDir = Split-Path -Parent $PSScriptRoot
$RepoDir = Split-Path -Parent $DesktopDir
$Runtime = [System.IO.Path]::GetFullPath($OutputPath)
$Parent = Split-Path -Parent $Runtime

if (Test-Path -LiteralPath $Runtime) {
  throw "OutputPath already exists; refusing to overwrite it: $Runtime"
}

New-Item -ItemType Directory -Path $Parent -Force | Out-Null
$Staging = Join-Path $Parent (".mathtutor-python-runtime-" + [guid]::NewGuid().ToString("N"))
$Archive = Join-Path $Staging $ArchiveName
$Expanded = Join-Path $Staging "runtime"

try {
  New-Item -ItemType Directory -Path $Staging, $Expanded -Force | Out-Null
  Invoke-WebRequest -Uri $ArchiveUrl -OutFile $Archive
  $Hasher = [System.Security.Cryptography.SHA256]::Create()
  $ArchiveStream = [System.IO.File]::OpenRead($Archive)
  try {
    $ActualSha256 = -join ($Hasher.ComputeHash($ArchiveStream) | ForEach-Object {
      $_.ToString("x2")
    })
  } finally {
    $ArchiveStream.Dispose()
    $Hasher.Dispose()
  }
  if ($ActualSha256 -ne $ArchiveSha256) {
    throw "Python runtime checksum mismatch: expected $ArchiveSha256, got $ActualSha256"
  }

  Expand-Archive -LiteralPath $Archive -DestinationPath $Expanded
  $Pth = Join-Path $Expanded "python312._pth"
  if (-not (Test-Path -LiteralPath $Pth -PathType Leaf)) {
    throw "Embedded Python path configuration is missing: $Pth"
  }

  # Keep the runtime isolated from user/global Python while allowing the
  # packaged MathTutor source in the sibling resources/python-app directory.
  @(
    "python312.zip"
    "."
    "Lib"
    "Lib/site-packages"
    "../python-app"
    "import site"
  ) | Set-Content -LiteralPath $Pth -Encoding ascii

  $SitePackages = Join-Path $Expanded "Lib\site-packages"
  New-Item -ItemType Directory -Path $SitePackages -Force | Out-Null
  & $BuildPython @BuildPythonArgs -m pip install `
    --disable-pip-version-check --no-compile --target $SitePackages $RepoDir
  if ($LASTEXITCODE -ne 0) {
    throw "Installing MathTutor runtime dependencies failed with exit code $LASTEXITCODE"
  }

  # Product source is copied separately through the audited package allowlist.
  Get-ChildItem -LiteralPath $SitePackages -Force | Where-Object {
    $_.Name -eq "mathtutor" -or $_.Name -like "mathtutor-*.dist-info"
  } | Remove-Item -Recurse -Force

  $Probe = @"
import sys
sys.path.insert(0, r'$($RepoDir.Replace("'", "''"))\src')
import aiosqlite, alembic, bcrypt, fastapi, httpx, jose, pydantic, pypdf, sqlalchemy, sqlcipher3, uvicorn
import mathtutor.standalone
assert sys.version_info[:2] == (3, 12), sys.version
print(sys.version)
print(mathtutor.standalone.__file__)
"@
  & (Join-Path $Expanded "python.exe") -I -c $Probe
  if ($LASTEXITCODE -ne 0) {
    throw "The assembled Python runtime failed its import probe."
  }

  Move-Item -LiteralPath $Expanded -Destination $Runtime
  Write-Output "Windows Python runtime ready: $Runtime"
} finally {
  if (Test-Path -LiteralPath $Staging) {
    Remove-Item -LiteralPath $Staging -Recurse -Force
  }
}
