"""Standalone desktop-app entry point, without personal custom buttons."""

import sys
from pathlib import Path


def graph_file_argument(arguments):
    """Accept a file opened by the desktop, or the explicit --graph option."""
    if len(arguments) == 2 and arguments[0] == '--graph':
        return Path(arguments[1])
    if len(arguments) == 1 and Path(arguments[0]).suffix.lower() in {
            '.graphml', '.g6', '.graph6', '.s6', '.sparse6', '.d6', '.digraph6'}:
        return Path(arguments[0])
    return None


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--graph-info-worker':
        from graph_builder_core.algorithms.metrics import worker_from_files
        worker_from_files(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        from graph_builder import main
        graph_file = graph_file_argument(sys.argv[1:])
        raise SystemExit(main(actions=[], graph_file=graph_file,
                              untitled=graph_file is None,
                              tutorial_on_first_run=True))
