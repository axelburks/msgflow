import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


ROOT_DIR = Path(SPECPATH).resolve().parents[1]
datas = collect_data_files("msgflow") + copy_metadata("msgflow")
hiddenimports = collect_submodules("msgflow")
APP_ICON = ROOT_DIR / "src" / "msgflow" / "resources" / "icon.icns"


def project_version():
    version = os.environ.get("MSGFLOW_VERSION")
    if version:
        return version
    text = (ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if match is None:
        raise RuntimeError("pyproject.toml does not define [project].version")
    return match.group(1)


APP_VERSION = project_version()

a = Analysis(
    [str(ROOT_DIR / "app.py")],
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
    name="msgflow-app",
    console=False,
)
app = BUNDLE(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="msgflow.app",
    icon=str(APP_ICON),
    bundle_identifier="com.axel.msgflow",
    info_plist={
        "CFBundleDisplayName": "msgflow",
        "CFBundleName": "msgflow",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "11.0",
        "LSUIElement": True,
    },
)
