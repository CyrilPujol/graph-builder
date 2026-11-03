"""Check that the frozen editor starts outside the source checkout."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

from build_app import _platform_details


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
    with tempfile.TemporaryDirectory(prefix='graph-builder-smoke-') as directory:
        extracted = Path(directory) / 'extracted'
        extracted.mkdir()
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
        process = subprocess.Popen([str(executable)], cwd=directory,
                                   env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(4)
            if process.poll() is not None:
                _, errors = process.communicate(timeout=5)
                raise RuntimeError(f'Packaged app exited early ({process.returncode}):\n{errors}')
            print('Packaged app started and remained open outside the source tree.')
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


if __name__ == '__main__':
    main()
