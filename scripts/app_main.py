"""Standalone desktop-app entry point, without personal custom buttons."""

import sys


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--graph-info-worker':
        from graph_builder_core.info import worker_from_files
        worker_from_files(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        from graph_builder import main
        raise SystemExit(main(actions=[], untitled=True))
