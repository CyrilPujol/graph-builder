"""Build a self-contained Graph Builder download for the current operating system.

Run from the repository root after ``python -m pip install --no-user -e '.[build]'``.
Builds must run separately on macOS, Windows, and Linux.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'local/build'
DIST = ROOT / 'local/dist'
NAME = 'Graph Builder'


def _platform_details():
    system = platform.system()
    machine = platform.machine().lower()
    architecture = 'arm64' if machine in {'arm64', 'aarch64'} else 'x64'
    if system == 'Darwin':
        return 'macOS', architecture, ROOT / 'assets/icons/graph_builder.icns'
    if system == 'Windows':
        return 'Windows', architecture, ROOT / 'assets/icons/graph_builder.ico'
    if system == 'Linux':
        return 'Linux', architecture, ROOT / 'assets/icons/graph_builder.png'
    raise RuntimeError(f'Unsupported build platform: {system}')


def _archive(folder: Path, destination: Path, system: str):
    if system == 'macOS':
        # ditto preserves the app bundle's symlinks, permissions and resources.
        subprocess.run(['ditto', '-c', '-k', '--keepParent', str(folder),
                        str(destination)], check=True)
    elif system == 'Linux':
        with tarfile.open(destination, 'w:gz') as archive:
            archive.add(folder, arcname=folder.name)
    else:
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            for item in folder.rglob('*'):
                if item.is_file():
                    archive.write(item, item.relative_to(DIST))


def main():
    system, architecture, icon = _platform_details()
    BUILD.mkdir(parents=True, exist_ok=True)
    build_environment = os.environ.copy()
    build_environment['PYINSTALLER_CONFIG_DIR'] = str(BUILD / 'pyinstaller-config')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--windowed', '--onedir', '--name', NAME, '--icon', str(icon),
        '--paths', str(ROOT),
        '--distpath', str(DIST), '--workpath', str(BUILD / 'pyinstaller'),
        '--specpath', str(BUILD), str(ROOT / 'scripts/app_main.py'),
    ], check=True, cwd=ROOT, env=build_environment)

    built = DIST / (NAME + '.app' if system == 'macOS' else NAME)
    if not built.exists():
        raise RuntimeError(f'Build completed without expected output: {built}')
    extension = '.tar.gz' if system == 'Linux' else '.zip'
    destination = DIST / f'GraphBuilder-{system}-{architecture}{extension}'
    if destination.exists():
        destination.unlink()
    _archive(built, destination, system)
    print(f'Created {destination}')


if __name__ == '__main__':
    main()
