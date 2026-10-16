"""Install the built NSIS package and exercise its normal GUI startup path."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request


EXPECTED_VERSION = json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text(encoding='utf-8'))['version']


def clean_environment(data: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('MATHTUTOR_', 'PYTHON', 'CONDA', 'NODE_'))
           and key.upper() not in ('ELECTRON_RUN_AS_NODE', 'VIRTUAL_ENV', 'WEB_CONCURRENCY', 'PATH')}
    system = Path(os.environ['SystemRoot'])
    env.update(PATH=f'{system / "System32"};{system}', MATHTUTOR_DATA_ROOT=str(data),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    return env


def kill_tree(process):
    if process.poll() is None:
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    process.wait(timeout=15)


def stop_installer_autostart(executable):
    # Some NSIS configurations open the app at finish. Only stop processes
    # from this disposable installation, never other MathTutor installations.
    script = "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $env:MATHTUTOR_SMOKE_EXECUTABLE } | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env={**os.environ, 'MATHTUTOR_SMOKE_EXECUTABLE': str(executable)},
                            capture_output=True, text=True, check=True, timeout=20)
    pids = json.loads(result.stdout) if result.stdout.strip() else []
    for pid in pids if isinstance(pids, list) else [pids]:
        subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'], capture_output=True)


def probe(python, data, code):
    result = subprocess.run([str(python), '-I', '-B', '-c', code], env=clean_environment(data),
                            capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr.decode('utf-8', errors='replace'))
    return json.loads(result.stdout.decode('utf-8'))


def local_api(base, path, *, method='GET', payload=None, file=None, operation_id=None, expected_status=200):
    """Only call this GUI instance's loopback API; never a provider endpoint."""
    assert re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', base), 'loopback API required'
    assert path.startswith('/api/v2/math-tutor/desktop/community/plugins'), 'plugin API required'
    headers = {'Origin': base}
    body = None
    if file is not None:
        filename, source = file
        assert re.fullmatch(r'[a-z][a-z0-9_-]+\.(?:py|ts)', filename)
        boundary = 'MathTutorStartupAcceptanceBoundary'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="operation_id"\r\n\r\n{operation_id}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                'Content-Type: text/plain; charset=utf-8\r\n\r\n').encode('ascii')
        body += source.encode('utf-8') + f'\r\n--{boundary}--\r\n'.encode('ascii')
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    elif payload is not None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    # Ignore machine HTTP_PROXY/HTTPS_PROXY settings even for localhost: smoke
    # requests must reach the installed service, not an external proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        value = json.loads(response.read(256 * 1024).decode('utf-8'))
        assert response.code == expected_status, f'plugin API {method} {path}: status={response.code}, response={value}'
    return value


PYTHON_PLUGIN = '''def run(request):
    import sys
    from pathlib import Path
    marker = Path(request["config"]["marker"])
    executions = int(marker.read_text(encoding="utf-8")) + 1 if marker.exists() else 1
    marker.write_text(str(executions), encoding="utf-8")
    return {"text": request["text"], "answer": 6 * 7, "executions": executions,
            "runtime": "python", "executable": sys.executable,
            "isolated": sys.flags.isolated, "no_site": sys.flags.no_site}
'''

TYPESCRIPT_PLUGIN = '''import {existsSync, readFileSync, writeFileSync} from "node:fs";
type Input = {text: string; config: {marker: string}};
export function run(request: Input) {
    const marker: string = request.config.marker;
    const executions: number = existsSync(marker) ? Number(readFileSync(marker, "utf8")) + 1 : 1;
    writeFileSync(marker, String(executions), "utf8");
    return {text: request.text, answer: 6 * 7, executions, runtime: "typescript",
            executable: process.execPath, node_version: process.versions.node};
}
'''


def verify_code_plugins(base, python, executable, data, *, environment):
    """Real raw-source import/consent/process/replay, with no model request."""
    expected_path = [str(Path(os.environ['SystemRoot']) / 'System32'), str(Path(os.environ['SystemRoot']))]
    assert environment['PATH'].split(';') == expected_path, 'GUI smoke PATH contains non-system runtimes'
    root = data / 'plugin-acceptance'
    root.mkdir(parents=True, exist_ok=True)
    result = {'status': 'PASS', 'provider_calls': 0, 'api': 'loopback_only',
              'system_only_gui_path': True, 'cases': []}
    prefix = '/api/v2/math-tutor/desktop/community/plugins'
    for runtime, suffix, source, expected_executable in (
            ('python', 'py', PYTHON_PLUGIN, python),
            ('typescript', 'ts', TYPESCRIPT_PLUGIN, executable)):
        marker = root / f'{runtime}-executions.txt'
        assert not marker.exists(), 'fresh code plugin marker already exists'
        receipt = local_api(base, prefix + '/import', method='POST',
            file=(f'{runtime}_acceptance.{suffix}', source), operation_id=f'startup-import-{runtime}')
        assert receipt['kind'] == 'plugin', receipt
        record = receipt['plugin']
        assert record['kind'] == 'code-plugin' and not record['enabled'] and not record['consented_permissions'], record
        assert record['runtime_available'], record
        plugin = record['plugin']
        assert plugin['runtime'] == runtime and plugin['required_permissions'] == ['execute_local_code'], plugin
        plugin_id = urllib.parse.quote(plugin['id'], safe='')
        path = prefix + '/' + plugin_id
        run_body = {'text': '中文插件验收🙂', 'config': {'marker': str(marker)},
                    'operation_id': f'startup-code-{runtime}-once'}
        assert not marker.exists(), 'import unexpectedly ran code'
        local_api(base, path + '/run', method='POST', payload=run_body, expected_status=409)
        assert not marker.exists(), 'disabled plugin unexpectedly ran code'
        enabled = local_api(base, path + '/enabled', method='PUT',
                            payload={'enabled': True, 'consent_permissions': ['execute_local_code']})
        assert enabled['enabled'] and enabled['consented_permissions'] == ['execute_local_code'], enabled
        assert not marker.exists(), 'enable unexpectedly ran code'
        first = local_api(base, path + '/run', method='POST', payload=run_body)
        repeated = local_api(base, path + '/run', method='POST', payload=run_body)
        assert repeated == first, 'same operation did not replay its original receipt'
        actual = first['data']
        assert actual['text'] == run_body['text'] and actual['answer'] == 42 and actual['executions'] == 1, actual
        assert marker.read_text(encoding='utf-8') == '1', 'replay executed code twice'
        assert actual['runtime'] == runtime, actual
        assert Path(actual['executable']).resolve() == expected_executable.resolve(), actual
        assert first['authority'] == 'reference_only' and first['sandboxed'] is False and first['read_only'] is False, first
        path_configuration = None
        if runtime == 'python':
            assert actual['isolated'] == 1, actual
            assert type(actual['no_site']) is int and actual['no_site'] in (0, 1), actual
            # The shipped Windows embeddable runtime pins its paths in this
            # file and explicitly opts into site. That configuration can make
            # no_site=0 despite -S; it is not a global/user Python dependency.
            pth = python.parent / 'python312._pth'
            if pth.is_file():
                entries = [line.strip() for line in pth.read_text(encoding='utf-8-sig').splitlines()
                           if line.strip() and not line.lstrip().startswith('#')]
                path_configuration = {'file': pth.name, 'entries': entries, 'import_site': 'import site' in entries}
            if actual['no_site'] == 0:
                assert path_configuration and path_configuration['import_site'], 'site enabled without packaged ._pth opt-in'
        else:
            assert actual['node_version'], actual
        evidence = {'runtime': runtime, 'status': 'PASS', 'plugin_id': plugin['id'],
            'command': record['command'], 'source_sha256': sha256(source.encode('utf-8')).hexdigest(),
            'explicit_local_code_consent': True, 'runtime_available': True, 'data': actual,
            'packaged_runtime': True, 'replayed_same_receipt': True, 'executions_after_replay': 1}
        if path_configuration is not None:
            evidence['python_path_configuration'] = path_configuration
        result['cases'].append(evidence)
        # Leave the disposable fresh profile safe for its subsequent relaunch;
        # disabling does not erase evidence or reset the execution ledger.
        disabled = local_api(base, path + '/enabled', method='PUT', payload={'enabled': False})
        assert disabled['enabled'] is False
    return result


SNAPSHOT = '''
import json, os
from pathlib import Path
from contextlib import closing
from mathtutor.infrastructure import db_crypto
root = Path(os.environ['MATHTUTOR_DATA_ROOT'])
rows = {}
for path in [root / 'math_tutor.db', *sorted((root / 'backups').glob('*pre-024-*.sqlite3'))]:
    with closing(db_crypto.connect(path, key=db_crypto.key_for_file(path))) as conn:
        revisions = conn.execute('SELECT version_num FROM alembic_version ORDER BY version_num').fetchall()
        sentinel_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='repair_sentinel'").fetchone()
        sentinel = conn.execute('SELECT value FROM repair_sentinel').fetchall() if sentinel_exists else []
        rows[path.name] = dict(revisions=revisions, sentinel=sentinel,
                               integrity=conn.execute('PRAGMA integrity_check').fetchall())
print(json.dumps(rows))
'''


def run_gui(executable, python, data, output, name, *, expect_failure=False):
    env = clean_environment(data)
    data.mkdir(parents=True, exist_ok=True)
    log = data / 'logs' / 'startup.log'
    started = time.monotonic()
    stdout_path, stderr_path = output / f'{name}.stdout.log', output / f'{name}.stderr.log'
    with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
        first = subprocess.Popen([str(executable)], env=env, stdout=stdout, stderr=stderr)
        second = None
        try:
            deadline = time.monotonic() + 90
            duplicate_started = False
            while time.monotonic() < deadline:
                text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
                if text and not duplicate_started and not expect_failure:
                    second = subprocess.Popen([str(executable)], env=env, stdout=stdout, stderr=stderr)
                    second.wait(timeout=15)
                    assert second.returncode == 0, f'duplicate instance exit={second.returncode}'
                    duplicate_started = True
                if 'FATAL:' in text:
                    assert expect_failure, text
                    assert '无法自动恢复' in text, text
                    elapsed = time.monotonic() - started
                    assert elapsed < 35, f'failure still waited for timeout: {elapsed}'
                    return dict(case=name, expected_failure_reported=True, seconds=round(elapsed, 3))
                if 'startup: ready' in text:
                    assert not expect_failure, 'invalid database unexpectedly started'
                    assert duplicate_started and first.poll() is None
                    port = re.search(r'backend: .*--port (\d+)', text).group(1)
                    base = f'http://127.0.0.1:{port}'
                    with urllib.request.urlopen(base + '/api/v2/math-tutor/desktop/readiness', timeout=5) as response:
                        readiness = json.load(response)
                    migration = readiness['checks']['migrations']
                    assert migration == 'ok', readiness
                    with urllib.request.urlopen(base + '/version', timeout=5) as response:
                        version = json.load(response)
                    assert version['version'] == EXPECTED_VERSION, version
                    ready_seconds = round(time.monotonic() - started, 3)
                    result = dict(case=name, seconds=ready_seconds,
                                  duplicate_exit=second.returncode, migration=migration,
                                  version=version['version'], databases=probe(python, data, SNAPSHOT))
                    if name == 'fresh_unicode':
                        result['code_plugins'] = verify_code_plugins(base, python, executable, data, environment=env)
                    return result
                assert first.poll() is None, f'first instance exited: {first.returncode}'
                time.sleep(.2)
            raise TimeoutError(f'normal GUI did not become ready: {name}')
        finally:
            if second is not None:
                kill_tree(second)
            kill_tree(first)
            if log.exists():
                (output / f'{name}.startup.log').write_bytes(log.read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert os.name == 'nt', 'Windows target required'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = dict(status='FAIL', cases=[])
    try:
        with tempfile.TemporaryDirectory(prefix='mathtutor-startup-') as temp:
            root = Path(temp)
            install = root / '安装目录 蛋蛋的app' / 'MathTutor'
            install.parent.mkdir(parents=True)
            installer = args.installer.resolve()
            # NSIS /D consumes the unquoted tail, including spaces, and must be last.
            installed = subprocess.run(f'"{installer}" /S /D={install}',
                                       env=clean_environment(root / 'installer-data'), timeout=120)
            assert installed.returncode == 0
            executable = install / 'MathTutor.exe'
            python = install / 'resources' / 'python-runtime' / 'python.exe'
            assert executable.exists() and python.exists()
            stop_installer_autostart(executable)
            report['install_path'] = str(install)
            normal_data = root / '全新用户数据'
            normal = run_gui(executable, python, normal_data, output, 'fresh_unicode')
            assert normal['databases']['math_tutor.db']['revisions'] == [['024']]
            assert len(normal['databases']) == 1, normal
            report['cases'].append(normal)
            # Exercise normal relaunch on exactly the same data directory.
            # Remove only the previous test log, so the ready marker cannot be stale.
            (normal_data / 'logs' / 'startup.log').unlink()
            restart = run_gui(executable, python, normal_data, output, 'restart_unicode')
            assert restart['databases']['math_tutor.db']['revisions'] == [['024']]
            report['cases'].append(restart)
            damaged_data = root / '异常版本 用户数据'
            damaged_data.mkdir()
            probe(python, damaged_data, '''
import json, os
from pathlib import Path
from contextlib import closing
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure import db_crypto
path = Path(os.environ['MATHTUTOR_DATA_ROOT']) / 'math_tutor.db'
upgrade_db(str(path))
with closing(db_crypto.connect_db(path)) as conn:
    conn.execute("INSERT INTO alembic_version VALUES ('023')")
    conn.execute('CREATE TABLE repair_sentinel (value TEXT)')
    conn.execute("INSERT INTO repair_sentinel VALUES ('preserve-original-data')")
    conn.commit()
print(json.dumps({'prepared': True}))
''')
            recovered = run_gui(executable, python, damaged_data, output, 'recover_023_024')
            live = recovered['databases'].pop('math_tutor.db')
            assert live['revisions'] == [['024']] and live['sentinel'] == [['preserve-original-data']]
            backup, = recovered['databases'].values()
            assert backup['revisions'] == [['023'], ['024']] and backup['sentinel'] == live['sentinel']
            recovered['databases']['math_tutor.db'] = live
            report['cases'].append(recovered)
            invalid_data = root / '未知版本 用户数据'
            invalid_data.mkdir()
            probe(python, invalid_data, '''
import json, os
from pathlib import Path
from contextlib import closing
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure import db_crypto
path = Path(os.environ['MATHTUTOR_DATA_ROOT']) / 'math_tutor.db'
upgrade_db(str(path))
with closing(db_crypto.connect_db(path)) as conn:
    conn.execute("INSERT INTO alembic_version VALUES ('future')")
    conn.commit()
print(json.dumps({'prepared': True}))
''')
            refused = run_gui(executable, python, invalid_data, output, 'reject_unknown_heads', expect_failure=True)
            refused['databases'] = probe(python, invalid_data, SNAPSHOT)
            assert refused['databases']['math_tutor.db']['revisions'] == [['024'], ['future']]
            report['cases'].append(refused)
        report['status'] = 'PASS'
    except BaseException:
        report['error'] = traceback.format_exc()
        raise
    finally:
        (output / 'startup-acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
