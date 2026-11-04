"""Launch the Linux bundle in a minimal Ubuntu container without build packages."""

from __future__ import annotations

import subprocess
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


if __name__ == '__main__':
    main()
