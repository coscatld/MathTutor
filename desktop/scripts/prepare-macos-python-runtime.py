"""Prepare an explicitly pinned standalone macOS archive, never hosted Python.

The release maintainer supplies an install-only relocatable CPython archive URL
and its independently verified SHA256. Build Python only orchestrates extraction;
all dependency installation runs with the extracted target interpreter.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive-url', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('macOS arm64 runtime must be prepared on a macOS arm64 runner')
    if not args.archive_url.startswith('https://') or len(args.sha256) != 64:
        raise SystemExit('An HTTPS target archive URL and pinned SHA256 are required')
    target = args.output.resolve()
    if target.exists():
        raise SystemExit(f'Refusing to overwrite existing runtime: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='macos-runtime-', dir=target.parent) as work:
        work = Path(work)
        archive = work / 'python.tar.gz'
        with urllib.request.urlopen(args.archive_url, timeout=60) as source, archive.open('wb') as output:
            shutil.copyfileobj(source, output)
        with archive.open('rb') as source:
            actual_sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual_sha256 != args.sha256.lower():
            raise SystemExit('Target Python archive checksum mismatch')
        unpacked = work / 'unpacked'
        with tarfile.open(archive) as package:
            package.extractall(unpacked, filter='data')
        runtime = unpacked / 'python'
        if not (runtime / 'bin/python3').is_file():
            raise SystemExit('Expected standalone install-only archive containing python/bin/python3')
        if not (runtime / 'bin/python').exists():
            (runtime / 'bin/python').symlink_to('python3')
        executable = runtime / 'bin/python'
        repo = Path(__file__).resolve().parents[2]
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV'))}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        subprocess.run([str(executable), '-I', '-c', "import platform,sys; assert sys.platform=='darwin' and platform.machine()=='arm64'; assert (3,11)<=sys.version_info[:2]<(3,14)"], check=True, env=env)
        subprocess.run([str(executable), '-I', '-m', 'pip', 'install', '--no-compile', str(repo)], check=True, env=env)
        # Source is packaged independently through the existing allowlist.
        for site in runtime.glob('lib/python*/site-packages'):
            for installed in [site / 'mathtutor', *site.glob('mathtutor-*.dist-info')]:
                if installed.exists():
                    shutil.rmtree(installed)
        shutil.move(str(runtime), target)
    print(f'macOS target runtime prepared: {target}')


if __name__ == '__main__':
    main()
