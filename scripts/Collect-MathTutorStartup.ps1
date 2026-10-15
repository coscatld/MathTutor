[CmdletBinding()]
param([string]$InstallDir)
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktop) { $desktop = $env:TEMP }
$output = Join-Path $desktop ('MathTutor-startup-diagnosis-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $output -Force | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$report = [ordered]@{ collected_at = (Get-Date -Format o); windows_version = [Environment]::OSVersion.VersionString; architecture = $env:PROCESSOR_ARCHITECTURE }
$registrations = @(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'MathTutor*' })
$report.installations = @($registrations | Select-Object DisplayName, DisplayVersion, InstallLocation, DisplayIcon)
$roots = @()
if ($InstallDir) { $roots += $InstallDir }
foreach ($entry in $registrations) {
  if ($entry.InstallLocation) { $roots += $entry.InstallLocation }
  if ($entry.DisplayIcon) {
    $icon = ($entry.DisplayIcon -replace ',\d+$','').Trim('"')
    if (Test-Path -LiteralPath $icon -PathType Leaf) { $roots += Split-Path -Parent $icon }
  }
}
$roots = @($roots | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'resources\python-runtime\python.exe') -PathType Leaf) } | Select-Object -Unique)
$report.detected_install_roots = $roots
$names = @('MATHTUTOR_PYTHON','MATHTUTOR_WEB_ROOT','MATHTUTOR_DATA_ROOT','MATHTUTOR_DB_PATH','PYTHONHOME','PYTHONPATH','ELECTRON_RUN_AS_NODE','WEB_CONCURRENCY')
$report.environment_overrides = @{}
foreach ($name in $names) { $value = [Environment]::GetEnvironmentVariable($name); if ($value) { $report.environment_overrides[$name] = $value } }
$report.processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $path = $_.ExecutablePath
  $path -and @($roots | Where-Object { $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
} | Select-Object Name, ProcessId, ParentProcessId, ExecutablePath)
$databases = @((Join-Path $env:APPDATA 'math-tutor-desktop\math_tutor.db'),(Join-Path $env:APPDATA 'MathTutor\math_tutor.db'))
if ($env:MATHTUTOR_DB_PATH) { $databases += $env:MATHTUTOR_DB_PATH }
if ($env:MATHTUTOR_DATA_ROOT) { $databases += Join-Path $env:MATHTUTOR_DATA_ROOT 'math_tutor.db' }
$pythonCode = @'
import importlib, json, pathlib, sqlite3, sys
report = {'executable': sys.executable, 'version': sys.version, 'imports': {}, 'databases': []}
for name in ['ssl', 'sqlite3', 'numpy', 'aiosqlite', 'alembic', 'fastapi', 'sqlalchemy', 'sqlcipher3', 'uvicorn']:
    try:
        module = importlib.import_module(name)
        report['imports'][name] = {'ok': True, 'file': getattr(module, '__file__', None)}
    except Exception as error:
        report['imports'][name] = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)}
for value in dict.fromkeys(sys.argv[1:]):
    path = pathlib.Path(value).resolve()
    item = {'path': str(path), 'exists': path.is_file()}
    if path.is_file():
        connection = None
        try:
            connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
            item['version_table_sql'] = connection.execute("SELECT sql FROM sqlite_master WHERE name='alembic_version'").fetchone()
            item['revisions'] = connection.execute('SELECT version_num FROM alembic_version').fetchall()
        except Exception as error:
            item['error'] = type(error).__name__ + ': ' + str(error)
        finally:
            if connection is not None:
                connection.close()
    report['databases'].append(item)
print(json.dumps(report, ensure_ascii=True, indent=2))
'@
$probe = Join-Path $output 'read-only-probe.py'
[IO.File]::WriteAllText($probe, $pythonCode, $utf8)
$index = 0
foreach ($root in $roots) {
  $index++
  $python = Join-Path $root 'resources\python-runtime\python.exe'
  $target = Join-Path $output ("runtime-$index.json")
  $errors = Join-Path $output ("runtime-$index.stderr.txt")
  try {
    $lines = & $python -I -B $probe @databases 2> $errors
    $report["runtime_${index}_exit_code"] = $LASTEXITCODE
    [IO.File]::WriteAllText($target, ($lines -join [Environment]::NewLine), $utf8)
  } catch { $report["runtime_${index}_launch_error"] = $_.Exception.Message }
}
[IO.File]::WriteAllText((Join-Path $output 'environment.json'), ($report | ConvertTo-Json -Depth 8), $utf8)
if (-not $roots.Count) { Write-Host 'Install location not found. Run again with -InstallDir pointing to the directory containing MathTutor.exe.' }
$archive = "$output.zip"
Compress-Archive -Path (Join-Path $output '*') -DestinationPath $archive -Force
Write-Host 'Report created:' $archive
Write-Host 'This collector does not start MathTutor or change its database. It records paths, runtime imports, processes, and migration-version rows only.'
