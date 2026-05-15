from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


ROOT_DIR = Path(SPECPATH).resolve().parents[1]
datas = collect_data_files("msgflow") + copy_metadata("msgflow")
hiddenimports = collect_submodules("msgflow")

a = Analysis(
    [str(ROOT_DIR / "core.py")],
    pathex=[str(ROOT_DIR / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="msgflow",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="msgflow",
)
