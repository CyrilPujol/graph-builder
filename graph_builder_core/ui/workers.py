"""Shared file-based protocol for cancellable graph computations.

Connect result/error handlers before calling start_worker. The caller owns
cancellation and result presentation. release_worker is safe to call twice.
"""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QProcess


def prepare_worker(parent, payload):
    process = QProcess(parent)
    process._worker_dir = tempfile.TemporaryDirectory(prefix='graph-builder-worker-')
    directory = Path(process._worker_dir.name)
    process._input_path = directory / 'input.json'
    process._result_path = directory / 'result.json'
    try:
        process._input_path.write_text(json.dumps(payload), encoding='utf-8')
    except Exception:
        release_worker(process)
        process.deleteLater()
        raise
    return process


def start_worker(process, kind):
    entry = (['--graph-info-worker'] if getattr(sys, 'frozen', False) else
             ['-m', 'graph_builder_core.algorithms.metrics', '--worker'])
    process.start(sys.executable, [*entry, kind, str(process._input_path),
                                   str(process._result_path)])


def release_worker(process):
    directory = getattr(process, '_worker_dir', None)
    if directory is not None:
        directory.cleanup()
        process._worker_dir = None
