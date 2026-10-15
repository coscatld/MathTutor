"""Inspect the released Windows installer; never use development app code."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
import urllib.request


def clean_env(data: Path) -> dict[str, str]:
    data.mkdir(parents=True, exist_ok=True)
    names = ('SystemRoot', 'WINDIR', 'ComSpec', 'TEMP', 'TMP', 'USERPROFILE')
    env = {name: os.environ[name] for name in names if name in os.environ}
    env['PATH'] = os.path.join(env['SystemRoot'], 'System32') + ';' + env['SystemRoot']
    env.update(APPDATA=str(data / 'roaming'), LOCALAPPDATA=str(data / 'local'), HOME=str(data),
               MATHTUTOR_DATA_ROOT=str(data), MATHTUTOR_DB_PATH=str(data / 'math_tutor.db'),
               MATHTUTOR_DESKTOP='1', MATHTUTOR_ENVIRONMENT='production',
               MATHTUTOR_AUTH_ENABLED='0', AUTH_ENABLED='0')
    for name in ('APPDATA', 'LOCALAPPDATA'):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def stop(process):
    if process.poll() is None:
        subprocess.run([os.path.join(os.environ['SystemRoot'], 'System32', 'taskkill.exe'),
                        '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def versions(data: Path):
    path = data / 'math_tutor.db'
    if not path.exists():
        return {'database_created': False}
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        return {'database_created': True,
                'heads': connection.execute('SELECT version_num FROM alembic_version').fetchall(),
                'version_table_sql': connection.execute("SELECT sql FROM sqlite_master WHERE name='alembic_version'").fetchone()}
    except sqlite3.Error as error:
        return {'database_created': True, 'error': str(error)}
    finally:
        connection.close()


def run_case(install: Path, data: Path, report: Path, label: str, *, electron=False):
    env = clean_env(data)
    python = install / 'resources/python-runtime/python.exe'
    result = {'case': label, 'install': str(install), 'data': str(data),
              'path_without_external_python_node': env['PATH']}
    probe = subprocess.run([str(python), '-I', '-c',
        "import json,sys,ssl,sqlite3,aiosqlite,alembic,fastapi,numpy,sqlalchemy,sqlcipher3,uvicorn,mathtutor.standalone; "
        "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'sys_path':sys.path,"
        "'imports':{m.__name__:m.__file__ for m in [aiosqlite,alembic,fastapi,numpy,sqlalchemy,sqlcipher3,uvicorn,mathtutor.standalone]}}))"],
        env=env, cwd=data, capture_output=True, timeout=30)
    result['import_probe'] = {'exit': probe.returncode, 'stdout': probe.stdout.decode('utf-8', 'replace'),
                              'stderr': probe.stderr.decode('utf-8', 'replace')}
    if probe.returncode:
        return result
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    command = ([str(install / 'MathTutor.exe'), '--enable-logging=stderr'] if electron else
               [str(python), '-m', 'uvicorn', '--factory', 'mathtutor.standalone:create_standalone_app',
                '--host', '127.0.0.1', '--port', str(port), '--log-level', 'info'])
    stdout_path, stderr_path = report / (label + '.stdout.log'), report / (label + '.stderr.log')
    started = time.monotonic()
    with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
        process = subprocess.Popen(command, env=env, cwd=data, stdout=stdout, stderr=stderr)
        try:
            while time.monotonic() - started < 85:
                if electron:
                    text = stdout_path.read_text(encoding='utf-8', errors='replace')
                    match = re.search(r'backend: .*?--port (\d+)', text)
                    if match:
                        port = int(match.group(1))
                    if 'FATAL:' in text:
                        result['shell_fatal'] = text[-6000:]
                        break
                try:
                    result['health'] = get_json(f'http://127.0.0.1:{port}/health')
                    result['health_ready_seconds'] = round(time.monotonic() - started, 3)
                    result['readiness'] = get_json(f'http://127.0.0.1:{port}/api/v2/math-tutor/desktop/readiness')
                    break
                except Exception as error:
                    result['last_poll_error'] = str(error)
                if process.poll() is not None:
                    result['early_exit'] = process.returncode
                    break
                time.sleep(0.3)
        finally:
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
            stop(process)
    result['database'] = versions(data)
    result['stderr_tail'] = stderr_path.read_text(encoding='utf-8', errors='replace')[-12000:]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    report = args.work / 'report'
    report.mkdir(parents=True, exist_ok=True)
    cases = []
    for label, data in [('unicode_install_ascii_data', 'ascii-profile-1'),
                        ('unicode_install_unicode_data', '用户数据一')]:
        cases.append(run_case(args.install, args.work / data, report, label))
        (report / 'diagnosis.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    ascii_install = args.work / 'ascii-install'
    args.install.rename(ascii_install)
    for label, data in [('ascii_install_ascii_data', 'ascii-profile-2'),
                        ('ascii_install_unicode_data', '用户数据二')]:
        cases.append(run_case(ascii_install, args.work / data, report, label))
        (report / 'diagnosis.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    cases.append(run_case(ascii_install, args.work / '用户数据三', report, 'electron_normal_start', electron=True))
    (report / 'diagnosis.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(cases, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
