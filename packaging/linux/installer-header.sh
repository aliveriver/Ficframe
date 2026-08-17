#!/bin/sh
set -eu

APP_NAME="FicFrame"
TARGET=""
LAUNCH=0

usage() {
  echo "用法：$0 --target /目标/目录 [--launch]"
  echo "也可以直接运行安装器并按提示输入目录。"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      TARGET=$2
      shift 2
      ;;
    --launch)
      LAUNCH=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -z "$TARGET" ]; then
        TARGET=$1
        shift
      else
        usage
        exit 2
      fi
      ;;
  esac
done

if [ -z "$TARGET" ]; then
  if [ -t 0 ]; then
    printf '请输入 FicFrame 安装目录（例如 /mnt/data/FicFrame）： '
    IFS= read -r TARGET
  else
    echo "错误：非交互安装必须通过 --target 指定安装目录。" >&2
    exit 2
  fi
fi

[ -n "$TARGET" ] || { echo "错误：安装目录不能为空。" >&2; exit 2; }
case "$TARGET" in
  /|/bin|/boot|/dev|/etc|/lib|/lib64|/proc|/root|/run|/sbin|/sys|/usr|/var)
    echo "错误：不能直接安装到系统目录 $TARGET。请指定其下的应用子目录或其他磁盘。" >&2
    exit 2
    ;;
esac

TARGET=$(mkdir -p "$TARGET" && cd "$TARGET" && pwd)
ARCHIVE_LINE=$(awk '/^__FICFRAME_ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$0")
[ -n "$ARCHIVE_LINE" ] || { echo "错误：安装包数据不完整。" >&2; exit 1; }

echo "正在安装到：$TARGET"
tail -n +"$ARCHIVE_LINE" "$0" | tar -xzf - -C "$TARGET" --strip-components=1
chmod +x "$TARGET/FicFrame"
mkdir -p "$TARGET/data"

echo "安装完成。"
echo "程序：$TARGET/FicFrame"
echo "配置、日志和生成结果：$TARGET/data"

if [ "$LAUNCH" -eq 1 ]; then
  cd "$TARGET"
  exec "$TARGET/FicFrame"
fi
exit 0

__FICFRAME_ARCHIVE_BELOW__
