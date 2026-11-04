"""Build a self-contained Graph Builder download for the current operating system.

Run from the repository root after ``python -m pip install --no-user -e '.[build]'``.
Builds must run separately on macOS, Windows, and Linux.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'local/build'
DIST = ROOT / 'local/dist'
NAME = 'Graph Builder'
LINUX_GRAPHICS_LIBRARIES = (
    'libEGL.so.1', 'libGL.so.1', 'libGLX.so.0',
    'libGLdispatch.so.0', 'libOpenGL.so.0', 'libGLESv2.so.2',
)
LINUX_HOST_LIBRARIES = {
    # These belong to glibc and must come from the target machine.
    'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2',
    'librt.so.1', 'libutil.so.1', 'libresolv.so.2', 'libanl.so.1',
}


def _linux_shared_library(name, cache):
    """Find a loadable system library for explicit PyInstaller inclusion."""
    import ctypes

    for line in cache.splitlines():
        match = re.match(rf'\s*{re.escape(name)}\s+\(.*\)\s+=>\s+(\S+)', line)
        if match:
            path = Path(match.group(1))
            if path.is_file():
                try:
                    ctypes.CDLL(str(path))
                except OSError:
                    continue
                return path
    raise RuntimeError(f'Cannot load {name}. Install the Linux graphics '
                       'runtime libraries before building.')


def _linux_dependencies(binary):
    """Read the shared libraries needed by a packaged ELF binary."""
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Cannot inspect Linux dependencies of {binary}: '
                           f'{result.stdout}{result.stderr}')
    for line in result.stdout.splitlines():
        missing = re.match(r'\s*(\S+)\s+=>\s+not found', line)
        if missing:
            raise RuntimeError(f'{binary} needs {missing.group(1)}, which is '
                               'not installed on the build machine.')
        match = re.match(r'\s*(\S+)\s+=>\s+(/\S+)\s+\(', line)
        if match:
            yield match.group(1), Path(match.group(2))


def _bundle_linux_dependencies(built):
    """Include the non-glibc dependency closure of the packaged app."""
    packaged = {path.name for path in built.rglob('*') if path.is_file()}
    binaries = []
    for path in built.rglob('*'):
        if path.is_file():
            with path.open('rb') as source:
                if source.read(4) == b'\x7fELF':
                    binaries.append(path)
    destination = built / '_internal'
    for binary in binaries:
        for name, source in _linux_dependencies(binary):
            if name in LINUX_HOST_LIBRARIES or name in packaged:
                continue
            if not source.is_file():
                raise RuntimeError(f'Cannot bundle missing library {source}')
            destination.mkdir(exist_ok=True)
            target = destination / name
            shutil.copy2(source, target)
            packaged.add(name)
            binaries.append(target)
    return packaged


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
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--windowed', '--onedir', '--name', NAME, '--icon', str(icon),
        '--paths', str(ROOT),
        '--distpath', str(DIST), '--workpath', str(BUILD / 'pyinstaller'),
        '--specpath', str(BUILD),
    ]
    if system == 'Linux':
        try:
            library_cache = subprocess.check_output(['ldconfig', '-p'], text=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError('Cannot locate Linux graphics libraries. '
                               'Install ldconfig and the graphics runtimes.') from exc
        for name in LINUX_GRAPHICS_LIBRARIES:
            command.extend(('--add-binary', f'{_linux_shared_library(name, library_cache)}:.'))
    command.append(str(ROOT / 'scripts/app_main.py'))
    subprocess.run(command, check=True, cwd=ROOT, env=build_environment)

    built = DIST / (NAME + '.app' if system == 'macOS' else NAME)
    if not built.exists():
        raise RuntimeError(f'Build completed without expected output: {built}')
    if system == 'Linux':
        present = _bundle_linux_dependencies(built)
        required = set(LINUX_GRAPHICS_LIBRARIES) | {
            'libxcb-image.so.0', 'libxcb-shape.so.0',
            'libxkbcommon-x11.so.0', 'libxcb-cursor.so.0',
            'libxcb-render-util.so.0', 'libxcb-util.so.1',
            'libxcb-icccm.so.4', 'libxcb-keysyms.so.1',
            'libxcb-xkb.so.1',
        }
        missing = required - present
        if missing:
            raise RuntimeError('Linux bundle is missing native Qt libraries: '
                               + ', '.join(sorted(missing)))
    extension = '.tar.gz' if system == 'Linux' else '.zip'
    destination = DIST / f'GraphBuilder-{system}-{architecture}{extension}'
    if destination.exists():
        destination.unlink()
    _archive(built, destination, system)
    print(f'Created {destination}')


if __name__ == '__main__':
    main()
