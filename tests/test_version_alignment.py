"""pyproject is the project version; each runtime/package declaration must agree."""
import json
from pathlib import Path
import subprocess
import tomllib
from mathtutor.release_config import RELEASE_CONFIG


def test_python_web_desktop_versions_agree():
    repo = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((repo / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    assert RELEASE_CONFIG.app_version == expected
    for folder in ('web', 'desktop', 'site'):
        package = json.loads((repo / folder / 'package.json').read_text(encoding='utf-8'))
        lock = json.loads((repo / folder / 'package-lock.json').read_text(encoding='utf-8'))
        assert package['version'] == lock['version'] == lock['packages']['']['version'] == expected
    frontend = subprocess.check_output(
        ['node', '-p', "require('./next.config.js').env.NEXT_PUBLIC_APP_VERSION"],
        cwd=repo / 'web', text=True,
    )
    assert frontend.strip() == expected
