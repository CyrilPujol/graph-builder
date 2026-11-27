"""Per-user document registration for the packaged desktop app."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def _windows_association_entries(executable, icon):
    """Cover both the registered GraphML type and Open with → Browse."""
    command = f'"{executable}" "%1"'
    document_icon = f'"{icon}",0'
    application = rf'Applications\{executable.name}'
    return (
        (r'GraphBuilder.GraphML', '', 'GraphML graph'),
        (r'GraphBuilder.GraphML\DefaultIcon', '', document_icon),
        (r'GraphBuilder.GraphML\shell\open\command', '', command),
        (r'GraphBuilder.GraphML\Application', 'ApplicationName', 'Graph Builder'),
        (r'GraphBuilder.GraphML\Application', 'ApplicationIcon', f'"{executable}",0'),
        (r'.graphml\OpenWithProgids', 'GraphBuilder.GraphML', ''),
        (application, 'FriendlyAppName', 'Graph Builder'),
        (application + r'\DefaultIcon', '', document_icon),
        (application + r'\SupportedTypes', '.graphml', ''),
        (application + r'\shell\open\command', '', command),
    )


def _notify_windows_associations():
    """Ask Explorer to refresh association information and cached icons."""
    import ctypes
    from ctypes import wintypes

    notify = ctypes.WinDLL('shell32', use_last_error=True).SHChangeNotify
    notify.argtypes = [wintypes.LONG, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
    notify.restype = None
    notify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED, SHCNF_IDLIST


def register_windows_documents():
    """Register the frozen Windows app without taking over any file defaults.

    Updates only this user's Graph Builder keys. Unchanged registrations are
    left alone. Moving the portable app updates its paths on the next launch.
    Library launches, other platforms, and smoke tests do not register anything.
    Registration is optional: a Windows policy denying it must not block launch.
    """
    if (sys.platform != 'win32' or not getattr(sys, 'frozen', False)
            or os.environ.get('GRAPH_BUILDER_SKIP_DESKTOP_REGISTRATION') == '1'):
        return False
    executable = Path(sys.executable).resolve()
    icon = executable.with_name('graphml_document.ico')
    if not executable.is_file() or not icon.is_file():
        return False

    import winreg

    try:
        changed = False
        for subkey, name, value in _windows_association_entries(executable, icon):
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                    'Software\\Classes\\' + subkey, 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
                    previous = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    previous = None
                if previous != (value, winreg.REG_SZ):
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    changed = True
        if changed:
            _notify_windows_associations()
        return True
    except OSError:
        logging.getLogger(__name__).warning('Could not register GraphML document icons.', exc_info=True)
        return False


def _desktop_exec_argument(executable):
    """Quote a literal path for both desktop-file string and Exec parsing."""
    value = str(executable).replace('%', '%%')
    value = ''.join('\\' + char if char in '\\"`$' else char for char in value)
    value = value.replace('\\', '\\\\').replace('\n', r'\n').replace('\r', r'\r').replace('\t', r'\t')
    return f'"{value}"'


def _write_registration_file(path, content):
    """Update our own registration files atomically, only when changed."""
    try:
        if path.read_bytes() == content:
            return
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _refresh_linux_cache(command, directory, cache, sources, *options):
    """Refresh changed metadata using available desktop tools, never a shell."""
    if cache.is_file() and all(source.stat().st_mtime_ns <= cache.stat().st_mtime_ns
                               for source in sources):
        return
    program = shutil.which(command)
    if program is None:
        logging.getLogger(__name__).warning('%s is unavailable. Desktop integration may be incomplete.', command)
        return
    environment = os.environ.copy()
    # Frozen Linux apps prepend private libraries. System tools need their own.
    original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is None:
        environment.pop('LD_LIBRARY_PATH', None)
    else:
        environment['LD_LIBRARY_PATH'] = original
    try:
        subprocess.run([program, *options, str(directory)], check=True, timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment)
    except (OSError, subprocess.SubprocessError):
        logging.getLogger(__name__).warning('Could not refresh %s.', command, exc_info=True)


def register_linux_documents():
    """Register this user's portable Linux app, without copying or defaults.

    Creates a menu entry, GraphML MIME description, and icons in XDG_DATA_HOME
    (normally ~/.local/share). Existing default-app choices are untouched.
    Paths are refreshed when the app is launched from a different location.
    """
    if (not sys.platform.startswith('linux') or not getattr(sys, 'frozen', False)
            or os.environ.get('GRAPH_BUILDER_SKIP_DESKTOP_REGISTRATION') == '1'):
        return False
    executable = Path(sys.executable).resolve()
    application_icon = executable.with_name('graph_builder.png')
    document_icon = executable.with_name('graphml_document.png')
    if not all(path.is_file() for path in (executable, application_icon, document_icon)):
        return False
    location = os.environ.get('XDG_DATA_HOME', '')
    data = Path(location) if location and Path(location).is_absolute() else Path.home() / '.local/share'
    applications = data / 'applications'
    mime = data / 'mime'
    theme = data / 'icons/hicolor'
    entry = applications / 'org.cyrilpujol.GraphBuilder.desktop'
    description = mime / 'packages/org.cyrilpujol.GraphBuilder.xml'
    icon_files = {
        theme / '256x256/apps/org.cyrilpujol.GraphBuilder.png': application_icon,
        theme / '256x256/mimetypes/application-graphml+xml.png': document_icon,
        theme / '256x256/mimetypes/application-x-graphml.png': document_icon,
    }
    desktop_text = (
        '[Desktop Entry]\nType=Application\nName=Graph Builder\n'
        'Comment=Edit and visualize GraphML graphs\n'
        f'Exec={_desktop_exec_argument(executable)} %f\n'
        'Icon=org.cyrilpujol.GraphBuilder\nTerminal=false\n'
        'Categories=Graphics;Education;\n'
        'MimeType=application/graphml+xml;application/x-graphml;\n'
    )
    mime_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        '  <mime-type type="application/graphml+xml">\n'
        '    <comment>GraphML graph</comment>\n'
        '    <alias type="application/x-graphml"/>\n'
        '    <sub-class-of type="application/xml"/>\n'
        '    <glob pattern="*.graphml" weight="80"/>\n'
        '    <root-XML namespaceURI="http://graphml.graphdrawing.org/xmlns" localName="graphml"/>\n'
        '    <icon name="application-graphml+xml"/>\n'
        '  </mime-type>\n</mime-info>\n'
    )
    try:
        _write_registration_file(entry, desktop_text.encode('utf-8'))
        _write_registration_file(description, mime_text.encode('utf-8'))
        for destination, source in icon_files.items():
            _write_registration_file(destination, source.read_bytes())
        _refresh_linux_cache('update-mime-database', mime, mime / 'mime.cache', [description])
        _refresh_linux_cache('update-desktop-database', applications,
                             applications / 'mimeinfo.cache', [entry])
        _refresh_linux_cache('gtk-update-icon-cache', theme, theme / 'icon-theme.cache',
                             icon_files, '-f', '-t')
        return True
    except OSError:
        logging.getLogger(__name__).warning('Could not register GraphML desktop integration.', exc_info=True)
        return False


def register_desktop_documents():
    """Register only packaged-app metadata appropriate to this platform."""
    if sys.platform == 'win32':
        return register_windows_documents()
    if sys.platform.startswith('linux'):
        return register_linux_documents()
    return False  # macOS document declarations are part of the .app bundle.
