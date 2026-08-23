from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "FicFrame"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    override = os.getenv("FICFRAME_RESOURCE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        bundle_root = getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        return Path(bundle_root).resolve()
    return project_root()


def install_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def user_data_root(create: bool = True) -> Path:
    override = os.getenv("FICFRAME_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser().resolve()
    elif not is_frozen():
        # 为开发者和 CLI 用户保留 repository 目录结构。
        root = project_root()
    else:
        # 发布版本保持便携：持久化文件存放在应用旁边，
        # 切换磁盘时配置、日志和生成图片也会随应用一起移动。
        root = install_root() / "data"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def web_root() -> Path:
    return resource_root() / "web"


def env_file() -> Path:
    return user_data_root() / ".env"


def providers_file() -> Path:
    return user_data_root() / ".ficframe" / "providers.json"


def outputs_root() -> Path:
    path = user_data_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path
