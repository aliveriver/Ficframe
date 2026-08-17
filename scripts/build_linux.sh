#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.uv-cache}"

HOST_OS="$(uname -s)"
case "$HOST_OS" in
  Linux) ;;
  *)
    echo "错误：Linux 发布包必须在原生 Linux 或 Linux CI 中构建，当前系统为 $HOST_OS。" >&2
    echo "PyInstaller 不支持从 Windows/Git Bash 交叉构建 Linux；请使用 GitHub Actions 或 Linux 虚拟机。" >&2
    exit 1
    ;;
esac
command -v file >/dev/null 2>&1 || { echo "错误：缺少 file 命令，无法验证 Linux 可执行文件格式。" >&2; exit 1; }

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(sed -nE 's/^version[[:space:]]*=[[:space:]]*"([^"]+)"/\1/p' pyproject.toml | head -n 1)"
fi
[[ -n "$VERSION" ]] || { echo "无法从 pyproject.toml 读取版本。" >&2; exit 1; }

BUILD_ROOT="$REPO_ROOT/build/package/linux"
DIST_ROOT="$BUILD_ROOT/dist"
WORK_ROOT="$BUILD_ROOT/work"
ARTIFACT_ROOT="$REPO_ROOT/release"
export UV_PROJECT_ENVIRONMENT="$BUILD_ROOT/.venv"
export UV_PYTHON_INSTALL_DIR="$BUILD_ROOT/python"
export PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/pyinstaller-cache"
export TMPDIR="$BUILD_ROOT/tmp"
case "$BUILD_ROOT" in
  "$REPO_ROOT"/build/package/linux) ;;
  *) echo "拒绝清理工作区之外的目录：$BUILD_ROOT" >&2; exit 1 ;;
esac
rm -rf -- "$BUILD_ROOT"
mkdir -p "$DIST_ROOT" "$WORK_ROOT" "$ARTIFACT_ROOT" "$TMPDIR" "$PYINSTALLER_CONFIG_DIR"

uv run --extra build pyinstaller --noconfirm --clean \
  --distpath "$DIST_ROOT" \
  --workpath "$WORK_ROOT" \
  "$REPO_ROOT/packaging/ficframe.spec"

APP_BINARY="$DIST_ROOT/FicFrame/FicFrame"
if [[ -e "$DIST_ROOT/FicFrame/FicFrame.exe" ]]; then
  echo "错误：构建结果是 Windows EXE，拒绝生成伪 Linux 压缩包。" >&2
  exit 1
fi
[[ -f "$APP_BINARY" ]] || { echo "错误：未找到 Linux 主程序 $APP_BINARY。" >&2; exit 1; }
BINARY_FORMAT="$(file -b "$APP_BINARY")"
case "$BINARY_FORMAT" in
  ELF\ *) ;;
  *)
    echo "错误：主程序不是 Linux ELF：$BINARY_FORMAT" >&2
    exit 1
    ;;
esac
chmod +x "$APP_BINARY"
echo "已验证 Linux 主程序：$BINARY_FORMAT"

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) RELEASE_ARCH="x86_64" ;;
  aarch64|arm64) RELEASE_ARCH="aarch64" ;;
  *) RELEASE_ARCH="$ARCH" ;;
esac

TARBALL="$ARTIFACT_ROOT/FicFrame-$VERSION-linux-$RELEASE_ARCH.tar.gz"
RUNFILE="$ARTIFACT_ROOT/FicFrame-$VERSION-linux-$RELEASE_ARCH.run"
rm -f -- "$TARBALL" "$RUNFILE"
tar -C "$DIST_ROOT" -czf "$TARBALL" FicFrame
cp "$REPO_ROOT/packaging/linux/installer-header.sh" "$RUNFILE"
cat "$TARBALL" >> "$RUNFILE"
chmod +x "$RUNFILE"

echo "Linux 构建完成："
echo "  $RUNFILE"
echo "  $TARBALL"
