# PyInstaller spec for the Windows release:  packaging\build.ps1  (or)
#   pyinstaller --noconfirm --distpath dist --workpath build packaging\opencaster.spec
#
# A one-folder build (fast start, fewer antivirus false alarms than one-file):
#   dist\OpenCaster\OpenCaster.exe             the app (no console)
#   dist\OpenCaster\OpenCaster (debug).exe     the same app with a console, for error messages
#   dist\OpenCaster\_internal\                 Python, Qt, spells, assets
# media\ is never bundled (not redistributable): users put their own next
# to the exe, where OpenCaster also keeps casts, profiles and settings.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "OpenCaster_GUI.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "spells"), "spells"),
        (str(ROOT / "opencaster" / "gui" / "assets"), "opencaster/gui/assets"),
    ],
    # bleak picks its Windows backend at run time; the winrt projections are
    # imported from inside it.
    hiddenimports=collect_submodules("bleak") + collect_submodules("winrt"),
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtDesigner",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)


def exe(name, console):
    return EXE(pyz, a.scripts, [], exclude_binaries=True, name=name, console=console,
               icon=str(ROOT / "opencaster" / "gui" / "assets" / "opencaster.ico"),
               upx=False, disable_windowed_traceback=False)


coll = COLLECT(
    exe("OpenCaster", console=False),
    exe("OpenCaster (debug)", console=True),
    a.binaries, a.datas,
    # TOC entries: (name in the bundle, source, type).  These two land in
    # _internal\; build.ps1 copies them next to the exe for the zip.
    [("README.txt", str(ROOT / "packaging" / "README.txt"), "DATA"),
     ("THIRD_PARTY_NOTICES.txt", str(ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt"), "DATA")],
    name="OpenCaster", upx=False,
)
