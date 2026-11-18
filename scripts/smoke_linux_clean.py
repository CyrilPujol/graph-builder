"""Launch the Linux bundle in a minimal Ubuntu container without build packages."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'local/dist/Graph Builder'


def main():
    if not (APP / 'Graph Builder').is_file():
        raise RuntimeError(f'No Linux app at {APP}')
    result = subprocess.run([
        'docker', 'run', '--rm', '--volume', f'{APP}:/app:ro',
        '--env', 'QT_QPA_PLATFORM=offscreen', 'ubuntu:22.04',
        'timeout', '5s', '/app/Graph Builder',
    ], capture_output=True, text=True, timeout=90)
    if result.returncode != 124:
        raise RuntimeError('Linux app did not stay open on clean Ubuntu '
                           f'(exit {result.returncode}):\n{result.stdout}\n{result.stderr}')
    print('Linux app started on clean Ubuntu without installed graphics libraries.')

    # The solver is loaded on demand, so opening the editor alone does not
    # exercise OR-Tools and its private native dependencies.
    with tempfile.TemporaryDirectory(prefix='graph-builder-linux-solver-') as directory:
        check_directory = Path(directory)
        (check_directory / 'graph.json').write_text(json.dumps({
            'directed': False, 'nodes': list(range(5)),
            'edges': [[node, (node + 1) % 5] for node in range(5)],
        }), encoding='utf-8')
        result = subprocess.run([
            'docker', 'run', '--rm', '--volume', f'{APP}:/app:ro',
            '--volume', f'{check_directory}:/checks',
            '--env', 'QT_QPA_PLATFORM=offscreen', 'ubuntu:22.04',
            '/app/Graph Builder', '--graph-info-worker', 'Solve:chromatic',
            '/checks/graph.json', '/checks/result.json',
        ], capture_output=True, text=True, timeout=45)
        output = check_directory / 'result.json'
        if result.returncode or not output.is_file():
            raise RuntimeError('Linux solver failed on clean Ubuntu '
                               f'(exit {result.returncode}):\n{result.stdout}\n{result.stderr}')
        solution = json.loads(output.read_text(encoding='utf-8'))
        if (solution.get('lower'), solution.get('upper'), solution.get('optimal')) != (3, 3, True):
            raise RuntimeError(f'Linux solver returned an unexpected result: {solution}')
    print('Linux solver correctly colored a five-cycle on clean Ubuntu.')


if __name__ == '__main__':
    main()
