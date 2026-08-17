from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


project_root = Path.cwd()
hidden_imports = collect_submodules("uvicorn")
data_files = [
    (str(project_root / "web"), "web"),
    (str(project_root / "docs"), "docs"),
    (str(project_root / "README.md"), "."),
    (str(project_root / "LICENSE"), "."),
]
data_files += copy_metadata("fastapi")
data_files += copy_metadata("uvicorn")

a = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "setuptools._vendor"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FicFrame",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FicFrame",
)
