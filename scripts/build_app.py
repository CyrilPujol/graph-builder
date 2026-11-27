"""Build a self-contained Graph Builder download for the current operating system.

Run from the repository root after ``python -m pip install --no-user -e '.[build,solver]'``.
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
MACOS_BUNDLE_ID = 'org.cyrilpujol.graphbuilder'
MACOS_GRAPHML_TYPE = 'org.cyrilpujol.graphbuilder.graphml'
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


def _linux_dependencies(binary, library_directory):
    """Read the shared libraries needed by a packaged ELF binary."""
    environment = os.environ.copy()
    # PyInstaller's bootloader searches _internal first. Running ldd without
    # that path falsely reports relocated wheel libraries (e.g. OR-Tools'
    # hashed Abseil libraries) as missing, even when they are bundled.
    # Do not let a build environment's extra paths hide missing bundle files.
    environment['LD_LIBRARY_PATH'] = str(library_directory.resolve())
    environment['LC_ALL'] = 'C'
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True,
                            env=environment)
    if result.returncode:
        raise RuntimeError(f'Cannot inspect Linux dependencies of {binary}: '
                           f'{result.stdout}{result.stderr}')
    for line in result.stdout.splitlines():
        missing = re.match(r'\s*(\S+)\s+=>\s+not found', line)
        if missing:
            raise RuntimeError(f'{binary} needs {missing.group(1)}, which was '
                               'not found in the bundle or system library paths.')
        # The application directory itself contains a space: Graph Builder.
        match = re.match(r'\s*(\S+)\s+=>\s+(/.+?)\s+\(0x[0-9a-fA-F]+\)', line)
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
        for name, source in _linux_dependencies(binary, destination):
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


def _add_macos_graphml_type(spec_path):
    """Register GraphML in PyInstaller's bundle before its ad-hoc signing."""
    source = spec_path.read_text(encoding='utf-8')
    marker = f'    bundle_identifier={MACOS_BUNDLE_ID!r},\n'
    if source.count(marker) != 1:
        raise RuntimeError('PyInstaller did not generate the expected macOS bundle entry.')
    document_type = (
        "    info_plist={'CFBundleDocumentTypes': [{\n"
        "        'CFBundleTypeName': 'GraphML document',\n"
        "        'CFBundleTypeExtensions': ['graphml'],\n"
        f"        'LSItemContentTypes': [{MACOS_GRAPHML_TYPE!r}],\n"
        "        'CFBundleTypeIconFile': 'graphml_document.icns',\n"
        "        'CFBundleTypeRole': 'Editor',\n"
        "        'LSHandlerRank': 'Alternate',\n"
        "    }], 'UTImportedTypeDeclarations': [{\n"
        f"        'UTTypeIdentifier': {MACOS_GRAPHML_TYPE!r},\n"
        "        'UTTypeDescription': 'GraphML graph',\n"
        "        'UTTypeIconFile': 'graphml_document.icns',\n"
        "        'UTTypeConformsTo': ['public.xml'],\n"
        "        'UTTypeTagSpecification': {\n"
        "            'public.filename-extension': ['graphml'],\n"
        "            'public.mime-type': ['application/graphml+xml'],\n"
        "        },\n"
        "    }]},\n"
    )
    spec_path.write_text(source.replace(marker, marker + document_type), encoding='utf-8')


def _build_macos_app(icon, environment):
    """Use a spec so document types are present before the bundle is signed."""
    spec_command = [
        sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec',
        '--windowed', '--onedir', '--name', NAME, '--icon', str(icon),
        '--add-data', f'{ROOT / "assets/icons/graphml_document.icns"}:.',
        '--paths', str(ROOT), '--hidden-import', 'ortools.sat.python.cp_model',
        '--osx-bundle-identifier', MACOS_BUNDLE_ID,
        '--specpath', str(BUILD), str(ROOT / 'scripts/app_main.py'),
    ]
    subprocess.run(spec_command, check=True, cwd=ROOT, env=environment)
    spec_path = BUILD / f'{NAME}.spec'
    _add_macos_graphml_type(spec_path)
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(DIST), '--workpath', str(BUILD / 'pyinstaller'),
        str(spec_path),
    ], check=True, cwd=ROOT, env=environment)


def main():
    system, architecture, icon = _platform_details()
    BUILD.mkdir(parents=True, exist_ok=True)
    build_environment = os.environ.copy()
    build_environment['PYINSTALLER_CONFIG_DIR'] = str(BUILD / 'pyinstaller-config')
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--windowed', '--onedir', '--name', NAME, '--icon', str(icon),
        '--paths', str(ROOT),
        '--hidden-import', 'ortools.sat.python.cp_model',
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
    if system == 'macOS':
        _build_macos_app(icon, build_environment)
    else:
        subprocess.run(command, check=True, cwd=ROOT, env=build_environment)

    built = DIST / (NAME + '.app' if system == 'macOS' else NAME)
    if not built.exists():
        raise RuntimeError(f'Build completed without expected output: {built}')
    if system == 'Windows':
        shutil.copy2(ROOT / 'assets/icons/graphml_document.ico',
                     built / 'graphml_document.ico')
    if system == 'Linux':
        shutil.copy2(icon, built / 'graph_builder.png')
        shutil.copy2(ROOT / 'assets/icons/graphml_document.png',
                     built / 'graphml_document.png')
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
