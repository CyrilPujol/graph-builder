# Building desktop downloads

The GitHub Actions workflow builds separate archives for macOS Apple Silicon, macOS Intel, Windows x64, and Linux x64. Open **Actions → Build desktop apps → Run workflow** to make test downloads. When a version tag such as `v0.1.0` is pushed, successful builds are attached to a GitHub release automatically. The release is not published if any platform build fails.

To build on your own computer, use Python 3.10 or newer on the target operating system. Open a terminal and replace the example path in `cd` with your project location.

On Linux, install your distribution's `libegl1` package before building. The packager needs its shared library available so it can include it in the download. The GitHub workflow also starts the finished Linux app in a clean Ubuntu container, where `libegl1` is not installed.

On macOS or Linux:

```sh
cd "/path/to/graph_builder"
python3 -m venv .venv
.venv/bin/python -m pip install --no-user -e '.[build]'
.venv/bin/python scripts/build_app.py
.venv/bin/python scripts/smoke_app.py
```

On Windows (PowerShell):

```powershell
cd "C:\path\to\graph_builder"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-user -e '.[build]'
.\.venv\Scripts\python.exe scripts/build_app.py
.\.venv\Scripts\python.exe scripts/smoke_app.py
```

The resulting app and distributable archive appear in `local/dist/`, away from the shared source files. A build for one OS cannot be produced on another OS. The archive has the icon in `assets/icons/` and uses `scripts/app_main.py`, which starts a new untitled graph with no personal buttons.

Before sharing a release, open the extracted archive on a fresh computer of each supported platform. Check that the app opens without Python installed, then create a graph, save it, reopen it, and export TikZ. Also try launching it from a directory outside the source checkout. See the README for the unsigned-app warning shown to first-time downloaders.
