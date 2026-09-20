"""Source verification must not invent a target distribution runtime."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


def load_check():
    spec = importlib.util.spec_from_file_location('source_check', Path(__file__).resolve().parents[1] / 'scripts/check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_verification_explicitly_skips_unprovisioned_distribution(monkeypatch, capsys, tmp_path):
    check = load_check()
    commands = []
    monkeypatch.delenv('MATHTUTOR_PYTHON_RUNTIME', raising=False)
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary.md'))
    monkeypatch.setattr(check.shutil, 'which', lambda _: 'npm')
    monkeypatch.setattr(check, 'run', lambda command, **kwargs: commands.append(command))
    check.main()
    assert ['npm', 'run', 'test:contracts'] in commands
    assert ['npm', 'run', 'test:distribution'] not in commands
    assert 'target packaging runtime not provisioned' in capsys.readouterr().out
    assert 'SKIPPED' in (tmp_path / 'summary.md').read_text(encoding='utf-8')


def test_provisioned_but_invalid_distribution_fails_check(monkeypatch):
    check = load_check()
    commands = []
    monkeypatch.setenv('MATHTUTOR_PYTHON_RUNTIME', '/invalid-target-fixture')
    monkeypatch.setattr(check.shutil, 'which', lambda _: 'npm')
    def run(command, **kwargs):
        commands.append(command)
        if 'test:distribution' in command:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(check, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        check.main()
    assert ['npm', 'run', 'test:distribution'] in commands


def test_verification_disables_telemetry_only_for_child_processes(monkeypatch, tmp_path):
    check = load_check()
    calls = []
    monkeypatch.setenv('NEXT_TELEMETRY_DISABLED', '0')
    monkeypatch.setenv('MATHTUTOR_CHECK_FIXTURE', 'preserved')
    monkeypatch.setattr(check.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)))
    check.run(['npm', 'run', 'build'], cwd=tmp_path)
    command, options = calls[0]
    assert command == ['npm', 'run', 'build']
    assert options['cwd'] == tmp_path and options['check'] is True
    assert options['env']['NEXT_TELEMETRY_DISABLED'] == '1'
    assert options['env']['MATHTUTOR_CHECK_FIXTURE'] == 'preserved'
    assert check.os.environ['NEXT_TELEMETRY_DISABLED'] == '0'
