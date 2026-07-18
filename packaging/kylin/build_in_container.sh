#!/usr/bin/env bash
set -euo pipefail

version="${1:?version is required}"
architecture="${2:?architecture is required}"
python_bin="/opt/python/cp312-cp312/bin/python"
root="$(cd "$(dirname "$0")/../.." && pwd)"
venv="/tmp/wxdoc-venv"

test "$(tr -d '\r\n' < "$root/VERSION")" = "$version"
mkdir -p "$HOME"
"$python_bin" -m venv "$venv"
"$venv/bin/python" -m pip install -e "$root[test,build]"
"$venv/bin/python" -m pytest "$root/tests"
"$venv/bin/python" "$root/tools/check_release.py" --tag "v$version"
"$venv/bin/python" "$root/packaging/build.py"

cp "$root/packaging/kylin/start.sh" "$root/dist/start.sh"
cp "$root/packaging/kylin/WXDocFormat.desktop" "$root/dist/WXDocFormat.desktop"
tar -C "$root/dist" -czf "$root/wx-doc-format-$version-kylin-v10-$architecture.tar.gz" \
  WXDocFormat start.sh WXDocFormat.desktop
