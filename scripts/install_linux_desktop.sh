#!/bin/sh
# Optional, per-user desktop integration for the extracted Linux app.
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}
installed_dir="$data_dir/graph-builder-app"
desktop_dir="$data_dir/applications"
mime_dir="$data_dir/mime"
icon_dir="$data_dir/icons/hicolor/256x256/apps"
mime_icon_dir="$data_dir/icons/hicolor/256x256/mimetypes"
desktop_id=org.cyrilpujol.GraphBuilder.desktop
mime_type=application/x-graphml

if [ ! -f "$source_dir/Graph Builder" ] || [ ! -d "$source_dir/_internal" ]; then
    printf 'Run this script from inside the extracted Graph Builder folder.\n' >&2
    exit 1
fi

mkdir -p "$installed_dir" "$desktop_dir" "$mime_dir/packages" "$icon_dir" "$mime_icon_dir"
if [ "$source_dir" != "$installed_dir" ]; then
    cp -R "$source_dir"/. "$installed_dir"/
fi
cp "$source_dir/graph_builder.png" "$icon_dir/org.cyrilpujol.GraphBuilder.png"
cp "$source_dir/graphml_document.png" "$mime_icon_dir/org.cyrilpujol.GraphBuilder-graphml.png"

# Desktop entries require extra escaping inside a quoted Exec path.
escaped_binary=$(printf '%s' "$installed_dir/Graph Builder" |
    sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/`/\\`/g' -e 's/\$/\\$/g')
{
    printf '[Desktop Entry]\n'
    printf 'Type=Application\n'
    printf 'Name=Graph Builder\n'
    printf 'Comment=Edit and visualize GraphML graphs\n'
    printf 'Exec="%s" %%f\n' "$escaped_binary"
    printf 'Icon=org.cyrilpujol.GraphBuilder\n'
    printf 'Terminal=false\n'
    printf 'Categories=Graphics;Education;\n'
    printf 'MimeType=%s;\n' "$mime_type"
} > "$desktop_dir/$desktop_id"

{
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
    printf '%s\n' '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">'
    printf '%s\n' '  <mime-type type="application/x-graphml">'
    printf '%s\n' '    <comment>GraphML graph</comment>'
    printf '%s\n' '    <icon name="org.cyrilpujol.GraphBuilder-graphml"/>'
    printf '%s\n' '    <glob pattern="*.graphml" weight="80"/>'
    printf '%s\n' '  </mime-type>'
    printf '%s\n' '</mime-info>'
} > "$mime_dir/packages/org.cyrilpujol.GraphBuilder.xml"

if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$mime_dir"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$desktop_dir"
fi
if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default "$desktop_id" "$mime_type"
    printf 'Graph Builder is installed for this user and set as the GraphML opener.\n'
else
    printf 'Graph Builder is installed. Choose it once in your file manager for .graphml files.\n'
fi
