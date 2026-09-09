[CmdletBinding()]
param(
  [string]$RuntimePath
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
  throw "Windows NSIS packages must be built on Windows."
}

$DesktopDir = Split-Path -Parent $PSScriptRoot
$RepoDir = Split-Path -Parent $DesktopDir
$WebDir = Join-Path $RepoDir "web"
if (-not $RuntimePath) {
  $RuntimePath = Join-Path $RepoDir ".runtime\python-win-x64"
}
$RuntimePath = [System.IO.Path]::GetFullPath($RuntimePath)

if (-not (Test-Path -LiteralPath (Join-Path $WebDir "node_modules") -PathType Container)) {
  throw "web/node_modules is missing; run npm ci in web/ first."
}
if (-not (Test-Path -LiteralPath (Join-Path $DesktopDir "node_modules") -PathType Container)) {
  throw "desktop/node_modules is missing; run npm ci in desktop/ first."
}

$PreviousTelemetry = $env:NEXT_TELEMETRY_DISABLED
$env:NEXT_TELEMETRY_DISABLED = "1"
try {
  Push-Location $WebDir
  try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Next.js production build failed." }
  } finally {
    Pop-Location
  }

  if (-not (Test-Path -LiteralPath (Join-Path $RuntimePath "python.exe") -PathType Leaf)) {
    & (Join-Path $PSScriptRoot "prepare-windows-python-runtime.ps1") -OutputPath $RuntimePath
  }

  $env:MATHTUTOR_PYTHON_RUNTIME = $RuntimePath
  & npm.cmd --prefix $DesktopDir run test:distribution
  if ($LASTEXITCODE -ne 0) { throw "Target runtime distribution verification failed." }
  # Some redirected Windows profiles report EXDEV for atomic renames inside
  # AppData. Keep electron-builder's extraction cache beside the local runtime.
  $env:ELECTRON_BUILDER_CACHE = Join-Path $RepoDir ".runtime\electron-builder-cache"
  # This local artifact is intentionally unsigned. Public distribution should
  # set up Authenticode credentials and remove this override.
  $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
  Push-Location $DesktopDir
  try {
    & (Join-Path $DesktopDir "node_modules\.bin\electron-builder.cmd") `
      --config electron-builder.config.cjs --win nsis --x64
    if ($LASTEXITCODE -ne 0) { throw "electron-builder failed." }
  } finally {
    Pop-Location
  }
} finally {
  $env:NEXT_TELEMETRY_DISABLED = $PreviousTelemetry
}
