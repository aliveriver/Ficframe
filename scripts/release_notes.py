"""Validate release metadata and render notes from CHANGELOG.md (standard library only)."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z]+)*")


def _assignment(text: str, key: str, source: str) -> str:
    matches = re.findall(rf"^{re.escape(key)}\s*=\s*[\"']([^\"']+)[\"']\s*(?:#.*)?$", text, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"Expected one {key} in {source}.")
    return matches[0]


def release_version(root: Path, requested: str = "") -> str:
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"^\[project\]\s*\n(.*?)(?=^\[|\Z)", project, re.MULTILINE | re.DOTALL)
    if section is None:
        raise ValueError("Missing [project] in pyproject.toml.")
    version = _assignment(section[1], "version", "pyproject.toml [project]")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    package_version = _assignment(
        (root / "ficframe" / "__init__.py").read_text(encoding="utf-8"),
        "__version__", "ficframe/__init__.py",
    )
    packages = re.split(r"^\[\[package\]\]\s*$", (root / "uv.lock").read_text(encoding="utf-8"), flags=re.MULTILINE)
    local_packages = [block for block in packages[1:] if re.search(r'^name\s*=\s*"ficframe"\s*$', block, re.MULTILINE)]
    if len(local_packages) != 1:
        raise ValueError("Expected one ficframe package in uv.lock.")
    lock_version = _assignment(local_packages[0], "version", "uv.lock ficframe package")
    if version != package_version or version != lock_version:
        raise ValueError(f"Version mismatch: pyproject={version}, package={package_version}, lock={lock_version}")
    if requested and requested != version:
        raise ValueError(f"Requested release {requested} does not match project version {version}.")
    return version


def extract_notes(changelog: str, version: str) -> str:
    """Read exactly one version section; ignore Markdown headings inside code fences."""
    lines = changelog.splitlines()
    headings: list[tuple[int, str]] = []
    fence: str = ""
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            continue
        heading = re.match(r"^##[ \t]+(.+?)\s*$", line)
        if not fence and heading:
            headings.append((index, heading[1]))
    expected = re.compile(rf"\[?v?{re.escape(version)}\]?(?:[ \t]+-[ \t]+.+)?")
    matches = [index for index, (_, heading) in enumerate(headings) if expected.fullmatch(heading)]
    if len(matches) != 1:
        raise ValueError(f"CHANGELOG.md must contain exactly one '## [{version}]' section; found {len(matches)}.")
    position = matches[0]
    start = headings[position][0] + 1
    end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
    notes = "\n".join(lines[start:end]).strip()
    content = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL)
    if not any(line.strip() and not line.lstrip().startswith("#") for line in content.splitlines()):
        raise ValueError(f"CHANGELOG.md section [{version}] has no update description.")
    return notes


def render_release_notes(version: str, notes: str) -> str:
    prefix = f"FicFrame-{version}"
    return f"""## 版本更新

{notes}

## 下载与安装

| 平台 | 安装器 | 便携版 |
| --- | --- | --- |
| Windows x64 | `{prefix}-windows-x64-setup.exe` | `{prefix}-windows-x64-portable.zip` |
| Linux x86_64 | `{prefix}-linux-x86_64.run` | `{prefix}-linux-x86_64.tar.gz` |

- Windows：运行安装器选择安装目录，或将便携 ZIP 完整解压后运行 `FicFrame.exe`。
- Linux：执行 `chmod +x {prefix}-linux-x86_64.run`，再运行 `./{prefix}-linux-x86_64.run --target /你的安装目录`。
- 更新前先关闭 FicFrame 并备份安装目录中的 `data/`；更新时保留该目录。
- `SHA256SUMS` 包含四个安装包的 SHA-256。Linux 可在下载目录执行 `sha256sum --check --ignore-missing SHA256SUMS`；Windows 可用 `Get-FileHash <安装包> -Algorithm SHA256` 对照。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="Requested version without v; defaults to pyproject.toml")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, help="GitHub Actions output file")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        version = release_version(root, args.version)
        notes = extract_notes((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_release_notes(version, notes), encoding="utf-8")
        if args.github_output:
            prerelease = re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"version={version}\ntag=v{version}\nprerelease={str(prerelease).lower()}\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Prepared release notes for v{version}: {args.output}")


if __name__ == "__main__":
    main()
