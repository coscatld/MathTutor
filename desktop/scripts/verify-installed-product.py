"""Run the portable UI acceptance driver against an actual installed application."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import traceback


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def preserve_disposable_evidence(data: Path, output: Path, report: dict) -> None:
    startup = data / 'logs' / 'startup.log'
    if startup.is_file():
        shutil.copy2(startup, output / 'wrapper-startup.log')
    database = data / 'math_tutor.db'
    if not database.is_file():
        return
    retained = output / 'synthetic-product-state.db'
    deadline = time.monotonic() + 10

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise TimeoutError('Evidence database snapshot exceeded10seconds')

    try:
        with sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True, timeout=5) as source:
            with sqlite3.connect(retained) as destination:
                source.backup(destination, pages=128, progress=progress)
        report['retained_database'] = {
            'path': retained.name,
            'sha256': digest(retained),
            'scope': 'Read-only evidence extraction from disposable synthetic acceptance data after app shutdown',
        }
    except (OSError, sqlite3.Error, TimeoutError) as error:
        report['evidence_snapshot_error'] = str(error)


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--installer', type=Path)
    source.add_argument('--executable', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, help='Original DMG/installer for installed artifact identity')
    parser.add_argument('--playwright-module', type=Path, required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--driver', type=Path, default=Path(__file__).with_name('installed-product-acceptance.mjs'))
    parser.add_argument('--result-file', default='installed-product-acceptance.json')
    parser.add_argument('--only')
    parser.add_argument('--timeout', type=int, default=2700)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert Path(args.result_file).name == args.result_file, 'Result file must be a basename'
    if (output / args.result_file).exists():
        raise SystemExit('Use a new output directory; previous acceptance evidence must not be overwritten.')
    assert args.playwright_module.is_file(), 'Playwright QA driver module is missing'
    driver = args.driver.resolve()
    assert driver.is_file(), 'Installed acceptance driver is missing'
    shutil.copy2(driver, output / 'driver-used.mjs')
    matrix = driver.with_name('installed-product-cases.json')
    if matrix.is_file():
        shutil.copy2(matrix, output / matrix.name)
    node = shutil.which(args.node) or str(Path(args.node).resolve())
    report = {'status': 'FAIL', 'installed_application': False, 'source_server': False,
              'provider_credentials_written': False, 'execution_scope': 'Actual installed Electron UI; injected failures separately labeled'}
    try:
        with tempfile.TemporaryDirectory(prefix='mathtutor-installed-acceptance-') as temporary:
            root = Path(temporary)
            installer_hash = digest(args.artifact.resolve()) if args.artifact else None
            if args.installer:
                assert os.name == 'nt', 'NSIS installer requires Windows'
                installer = args.installer.resolve()
                assert installer.is_file()
                installer_hash = digest(installer)
                spec = importlib.util.spec_from_file_location('installed_startup_helpers', Path(__file__).with_name('verify-installed-windows-startup.py'))
                helpers = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(helpers)
                install = root / '产品验收 安装目录' / 'MathTutor'
                install.parent.mkdir(parents=True)
                result = subprocess.run(f'"{installer}" /S /D={install}', env=helpers.clean_environment(root/'installer-data'), timeout=120)
                assert result.returncode == 0, f'NSIS exit {result.returncode}'
                executable = install / 'MathTutor.exe'
                assert executable.is_file()
                helpers.stop_installer_autostart(executable)
            else:
                executable = args.executable.resolve()
                assert executable.is_file()
            report.update(executable=str(executable), executable_sha256=digest(executable), installer_sha256=installer_hash)
            command = [node, str(driver), '--executable', str(executable), '--data-root', str(root/'独立验收数据'), '--output', str(output)]
            if installer_hash:
                command.extend(['--installer-sha256', installer_hash])
            if args.only:
                command.extend(['--only', args.only])
            environment = {**os.environ, 'PLAYWRIGHT_MODULE': str(args.playwright_module.resolve())}
            try:
                with (output/'driver.stdout.log').open('wb') as stdout, (output/'driver.stderr.log').open('wb') as stderr:
                    process = subprocess.Popen(command, cwd=root, env=environment, stdout=stdout, stderr=stderr,
                                               start_new_session=os.name != 'nt')
                    try:
                        exit_code = process.wait(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        report['forced_timeout_cleanup'] = {'owned_driver_pid': process.pid, 'normal_shutdown': False}
                        if os.name == 'nt':
                            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                           capture_output=True, timeout=30, check=False)
                        else:
                            os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            if os.name != 'nt':
                                os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=10)
                        raise
                report['driver_exit_code'] = exit_code
            finally:
                preserve_disposable_evidence(root / '独立验收数据', output, report)
            evidence = output / args.result_file
            assert evidence.is_file(), 'No installed product evidence was produced'
            result = json.loads(evidence.read_text(encoding='utf-8'))
            report['installed_application'] = bool(result.get('actual_installed_app') and result.get('identity', {}).get('electron', {}).get('packaged'))
            report['automatic_scope'] = result['automatic_scope']
            report['overall_product_acceptance'] = result['overall_product_acceptance']
            assert exit_code == 0, 'Installed UI acceptance had failed or blocked automatic cases; inspect retained evidence'
            report['status'] = 'AUTOMATIC_SCOPE_COMPLETE'
            report['not_a_full_product_pass'] = result['overall_product_acceptance'] != 'passed'
    except BaseException:
        report['error'] = traceback.format_exc()
        raise
    finally:
        (output/'installation-driver.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'status':report['status'],'output':str(output),'overall_product_acceptance':report.get('overall_product_acceptance','not_completed')},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
