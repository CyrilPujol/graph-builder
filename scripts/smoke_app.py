"""Check that the frozen editor starts outside the source checkout."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

from build_app import MACOS_GRAPHML_TYPE, _platform_details


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'local/dist'


def main():
    system, architecture, _ = _platform_details()
    extension = '.tar.gz' if system == 'Linux' else '.zip'
    archive = DIST / f'GraphBuilder-{system}-{architecture}{extension}'
    if not archive.is_file():
        raise RuntimeError(f'No packaged archive at {archive}')
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    # The extracted test copy is temporary and must not replace a real app's paths.
    environment['GRAPH_BUILDER_SKIP_DESKTOP_REGISTRATION'] = '1'
    with tempfile.TemporaryDirectory(prefix='graph-builder-smoke-') as directory:
        extracted = Path(directory) / 'extracted'
        extracted.mkdir()
        if system == 'Linux':
            environment.pop('GRAPH_BUILDER_SKIP_DESKTOP_REGISTRATION', None)
            environment['XDG_DATA_HOME'] = str(Path(directory) / 'desktop-data')
            environment['XDG_CONFIG_HOME'] = str(Path(directory) / 'desktop-config')
            environment['XDG_CACHE_HOME'] = str(Path(directory) / 'desktop-cache')
        if system == 'macOS':
            subprocess.run(['ditto', '-x', '-k', str(archive), str(extracted)], check=True)
            executable = extracted / 'Graph Builder.app/Contents/MacOS/Graph Builder'
        elif system == 'Windows':
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)
            executable = extracted / 'Graph Builder/Graph Builder.exe'
        else:
            with tarfile.open(archive, 'r:gz') as bundle:
                bundle.extractall(extracted)
            executable = extracted / 'Graph Builder/Graph Builder'
        if not executable.is_file():
            raise RuntimeError(f'No executable in archive at {executable}')
        if system == 'Windows' and not (executable.parent / 'graphml_document.ico').is_file():
            raise RuntimeError('Windows download is missing its GraphML document icon.')
        if system == 'macOS':
            plist_path = extracted / 'Graph Builder.app/Contents/Info.plist'
            with plist_path.open('rb') as source:
                metadata = plistlib.load(source)
            document_types = metadata.get('CFBundleDocumentTypes', ())
            if not any('graphml' in item.get('CFBundleTypeExtensions', ())
                       for item in document_types):
                raise RuntimeError('macOS bundle does not declare GraphML support.')
            if not any(item.get('CFBundleTypeIconFile') == 'graphml_document.icns'
                       for item in document_types):
                raise RuntimeError('macOS bundle does not declare a GraphML icon.')
            if not any(MACOS_GRAPHML_TYPE in item.get('LSItemContentTypes', ())
                       for item in document_types):
                raise RuntimeError('macOS bundle does not claim its GraphML content type.')
            imported = metadata.get('UTImportedTypeDeclarations', ())
            if not any(item.get('UTTypeIdentifier') == MACOS_GRAPHML_TYPE
                       and item.get('UTTypeIconFile') == 'graphml_document.icns'
                       for item in imported):
                raise RuntimeError('macOS bundle does not define its GraphML content type.')
            if not (extracted / 'Graph Builder.app/Contents/Resources/graphml_document.icns').is_file():
                raise RuntimeError('macOS bundle is missing its GraphML icon.')
        if system == 'Linux':
            folder = extracted / 'Graph Builder'
            if not (folder / 'graph_builder.png').is_file():
                raise RuntimeError('Linux download is missing its desktop icon.')
            if not (folder / 'graphml_document.png').is_file():
                raise RuntimeError('Linux download is missing its GraphML document icon.')
        process = subprocess.Popen([str(executable)], cwd=directory,
                                   env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(4)
            if process.poll() is not None:
                _, errors = process.communicate(timeout=5)
                raise RuntimeError(f'Packaged app exited early ({process.returncode}):\n{errors}')
            print('Packaged app started and remained open outside the source tree.')
            if system == 'Linux':
                data = Path(environment['XDG_DATA_HOME'])
                for relative in ('applications/org.cyrilpujol.GraphBuilder.desktop',
                                 'mime/packages/org.cyrilpujol.GraphBuilder.xml',
                                 'icons/hicolor/256x256/apps/org.cyrilpujol.GraphBuilder.png',
                                 'icons/hicolor/256x256/mimetypes/application-graphml+xml.png'):
                    if not (data / relative).is_file():
                        raise RuntimeError(f'Linux app did not register {relative}')
                if shutil.which('update-mime-database') and not (data / 'mime/mime.cache').is_file():
                    raise RuntimeError('Linux app did not refresh its MIME database.')
                validator = shutil.which('desktop-file-validate')
                if validator:
                    subprocess.run([validator, str(data / 'applications/org.cyrilpujol.GraphBuilder.desktop')],
                                   check=True, timeout=5)
                print('Packaged Linux app registered desktop metadata in an isolated user folder.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

        input_path = Path(directory) / 'graph.json'
        output_path = Path(directory) / 'result.json'
        input_path.write_text(json.dumps({'directed': False, 'nodes': [0, 1],
                                          'edges': [[0, 1]]}), encoding='utf-8')
        worker = subprocess.run([str(executable), '--graph-info-worker', 'Structure',
                                 str(input_path), str(output_path)], cwd=directory,
                                env=environment, capture_output=True, text=True, timeout=10)
        if worker.returncode or not output_path.is_file():
            raise RuntimeError(f'Packaged graph analysis failed: {worker.stderr}')
        if not any('Components: 1' in line for line in json.loads(output_path.read_text(encoding='utf-8'))):
            raise RuntimeError('Packaged graph analysis returned an unexpected result.')
        print('Packaged graph-analysis worker completed successfully.')
        optimized = subprocess.run([str(executable), '--graph-info-worker', 'Solve:chromatic',
                                    str(input_path), str(output_path)], cwd=directory,
                                   env=environment, capture_output=True, text=True, timeout=20)
        if optimized.returncode or not output_path.is_file():
            raise RuntimeError(f'Packaged graph solver failed: {optimized.stderr}')
        result = json.loads(output_path.read_text(encoding='utf-8'))
        if result.get('lower') != 2 or result.get('upper') != 2 or not result.get('optimal'):
            raise RuntimeError(f'Packaged graph solver returned an unexpected result: {result}')
        print('Packaged graph solver completed successfully.')


if __name__ == '__main__':
    main()
