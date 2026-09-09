"""pyproject is the project version; each runtime/package declaration must agree."""
import json
from pathlib import Path
import re
import tomllib
from mathtutor.release_config import RELEASE_CONFIG


def test_python_web_desktop_versions_agree():
    repo = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((repo / 'pyproject.toml').read_text())['project']['version']
    assert RELEASE_CONFIG.app_version == expected
    for folder in ('web', 'desktop'):
        package = json.loads((repo / folder / 'package.json').read_text())
        lock = json.loads((repo / folder / 'package-lock.json').read_text())
        assert package['version'] == lock['version'] == lock['packages']['']['version'] == expected
    frontend = (repo / 'web/next.config.js').read_text()
    assert re.search(r'NEXT_PUBLIC_APP_VERSION:\s*"([^"]+)"', frontend).group(1) == expected
