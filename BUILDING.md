# Building desktop downloads

The GitHub Actions workflow builds separate archives for macOS Apple Silicon, macOS Intel, Windows x64, and Linux x64. Open **Actions → Build desktop apps → Run workflow** to make test downloads. When a version tag such as `v0.2.0` is pushed, successful builds are attached to a GitHub release automatically. The release is not published if any platform build fails. Push the source commit before pushing its tag. Do not create a GitHub release manually beforehand, since this workflow creates it after all four builds pass.

To build on your own computer, use Python 3.10 or newer on the target operating system. Open a terminal and replace the example path in `cd` with your project location.

On Linux, install your distribution's OpenGL, EGL, and Qt XCB runtime libraries before building. The packager copies the native dependency chain into the download, except for glibc, which comes from the target system. The GitHub workflow also starts the finished Linux app and checks its bundled solver in a clean Ubuntu container without those build packages.

On macOS or Linux:

```sh
cd "/path/to/graph_builder"
python3 -m venv .venv
.venv/bin/python -m pip install --no-user -e '.[build,solver]'
.venv/bin/python scripts/build_app.py
.venv/bin/python scripts/smoke_app.py
```

On Windows (PowerShell):

```powershell
cd "C:\path\to\graph_builder"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-user -e '.[build,solver]'
.\.venv\Scripts\python.exe scripts/build_app.py
.\.venv\Scripts\python.exe scripts/smoke_app.py
```

The resulting app and distributable archive appear in `local/dist/`, away from the shared source files. A build for one OS cannot be produced on another OS. The archive has the icon in `assets/icons/` and uses `scripts/app_main.py`, which starts a new untitled graph with no personal buttons unless a graph file was opened. macOS declares GraphML support and includes a separate document-type icon. Windows and Linux automatically register their document icons. Windows covers both the named GraphML association and **Open with → Browse**. Linux also adds an application-menu entry and refreshes available desktop caches. Registration is per-user, does not copy the app or change default openers, and updates paths when the app moves. No custom icons are attached to saved files.

The smoke test disables Windows registration with `GRAPH_BUILDER_SKIP_DESKTOP_REGISTRATION=1`, so its temporary extracted copy cannot overwrite a real installation's registered paths. On Linux it instead tests registration in isolated XDG data, config, and cache folders. Standard desktop utilities are used when available, but missing tools must not block app startup.

The static GraphML document icon is generated from `assets/icons/graph_builder.png` by `scripts/make_document_icon.py`. To change its design later, edit that script and regenerate the three document icon assets with Pillow installed. Rebuild the desktop app afterward. A per-file picture of the graph would require a separate thumbnail provider for each operating system and is not provided by this app.

Before sharing a release, open the extracted archive on a fresh computer of each supported platform. Check that the app opens without Python installed, then create a graph, save it, and double-click the saved GraphML file after choosing Graph Builder as the default app. Also try opening a second GraphML file while the app is already running on macOS, then export TikZ. In Properties → Bounds, use **Compute** for the chromatic number of a five-cycle and check that it reports 3. Also try launching it from a directory outside the source checkout. See the README for the unsigned-app warning shown to first-time downloaders.
