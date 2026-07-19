#!/usr/bin/env bash
set -euo pipefail

version="${1:?version is required}"
architecture="${2:?architecture is required}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
venv="/tmp/wxdoc-venv"
python_version="3.12.13"
python_prefix="/tmp/cpython-shared"
python_bin="$python_prefix/bin/python3.12"
libffi_version="3.4.6"
libffi_prefix="/tmp/libffi"
bootstrap_python="/opt/python/cp312-cp312/bin/python"
wheelhouse="/tmp/wheelhouse"

test "$(tr -d '\r\n' < "$root/VERSION")" = "$version"
mkdir -p "$HOME"
mkdir -p "$wheelhouse"
"$bootstrap_python" -m pip download --dest "$wheelhouse" \
  "setuptools>=77" \
  wheel \
  "lxml==6.1.1" \
  "python-docx==1.2.0" \
  "pyinstaller==6.21.0" \
  "pytest==9.1.1"
curl --fail --location --retry 3 \
  "https://github.com/libffi/libffi/releases/download/v$libffi_version/libffi-$libffi_version.tar.gz" \
  --output "/tmp/libffi-$libffi_version.tar.gz"
tar -C /tmp -xzf "/tmp/libffi-$libffi_version.tar.gz"
cd "/tmp/libffi-$libffi_version"
./configure \
  --prefix="$libffi_prefix" \
  --disable-shared \
  --enable-static \
  --with-pic
make -j"$(getconf _NPROCESSORS_ONLN)"
make install

curl --fail --location --retry 3 \
  "https://www.python.org/ftp/python/$python_version/Python-$python_version.tgz" \
  --output "/tmp/Python-$python_version.tgz"
tar -C /tmp -xzf "/tmp/Python-$python_version.tgz"
cd "/tmp/Python-$python_version"
export PKG_CONFIG_PATH="$libffi_prefix/lib64/pkgconfig:$libffi_prefix/lib/pkgconfig"
pkg-config --exists libffi
export LIBFFI_CFLAGS="$(pkg-config --cflags libffi)"
export LIBFFI_LIBS="$(pkg-config --libs --static libffi)"
./configure \
  --prefix="$python_prefix" \
  --enable-shared \
  --with-ensurepip=install
make -j"$(getconf _NPROCESSORS_ONLN)"
make install
export LD_LIBRARY_PATH="$python_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PIP_NO_INDEX=1
export PIP_FIND_LINKS="$wheelhouse"
cd "$root"

"$python_bin" -m venv "$venv"
"$venv/bin/python" -m pip install -e "$root[test,build]"
"$venv/bin/python" -m pytest "$root/tests"
"$venv/bin/python" "$root/tools/check_release.py" --tag "v$version"
"$venv/bin/python" "$root/packaging/build.py"

cp "$root/packaging/kylin/start.sh" "$root/dist/start.sh"
cp "$root/packaging/kylin/MagicFormat.desktop" "$root/dist/MagicFormat.desktop"
tar -C "$root/dist" -czf "$root/wx-doc-format-$version-kylin-v10-$architecture.tar.gz" \
  MagicFormat start.sh MagicFormat.desktop
