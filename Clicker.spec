# PyInstaller build: python -m PyInstaller Clicker.spec
#   Windows: dist/Clicker/ (Clicker.exe and its libraries), which installer/clicker.iss packs into
#            Clicker-Setup.exe. A folder starts much faster than a one-file exe, which unpacks itself every launch.
#   macOS:   dist/Clicker.app
#   Linux:   dist/Clicker (one file)
# It leaves out the parts of Qt and Python that Clicker never uses, which keeps the app small.
import sys

from PyInstaller.utils.hooks import collect_submodules

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
backend = "_win32" if WIN else "_darwin" if MAC else "_xorg"

# Qt pieces pulled in by plugins but never used: QML/Quick (virtual keyboard), PDF, networking, Wayland/EGL.
QT_UNUSED = ("Qml", "Quick", "VirtualKeyboard", "Pdf", "Network", "OpenGL", "Wayland", "Wl", "EglFS")
QT_PLUGINS_KEEP = ("platforms", "platformthemes", "styles", "iconengines", "imageformats", "xcbglintegrations")
IMAGE_FORMATS_KEEP = ("qsvg", "qjpeg", "qico")


def wanted(dest):
    p = dest.replace("\\", "/")
    if p.endswith(("clicker.ico", "clicker.icns")):  # already built into the program's icon
        return False
    if "opencv_videoio_ffmpeg" in p:  # OpenCV's video reader/writer, loaded only for video files
        return False
    if "PySide6/" not in p:
        return True
    if "/translations/" in p:  # Clicker is English only
        return False
    if any(f"Qt6{m}" in p or f"Qt{m}." in p or f"Qt{m}.framework" in p for m in QT_UNUSED):
        return False
    if "/plugins/" in p:
        group = p.split("/plugins/", 1)[1].split("/", 1)[0]
        if group not in QT_PLUGINS_KEEP:
            return False
        if group == "imageformats" and not any(k in p for k in IMAGE_FORMATS_KEEP):
            return False
    return True


if WIN:
    import os
    sys.path.insert(0, os.path.abspath("."))
    from clicker.model import APP_VERSION
    nums = (tuple(int(n) for n in APP_VERSION.split(".")[:3]) + (0, 0, 0))[:3] + (0,)
    os.makedirs("build", exist_ok=True)
    with open("build/version_info.txt", "w", encoding="utf-8") as f:
        f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Clicker'), StringStruct('FileDescription', 'Clicker'),
    StringStruct('FileVersion', '{APP_VERSION}'), StringStruct('ProductName', 'Clicker'),
    StringStruct('ProductVersion', '{APP_VERSION}'), StringStruct('OriginalFilename', 'Clicker.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")

a = Analysis(
    ["clicker_app.py"],
    datas=[("assets", "assets")],
    hiddenimports=collect_submodules("clicker") + [f"pynput.keyboard.{backend}", f"pynput.mouse.{backend}"],
    excludes=["tkinter", "PIL", "yaml", "pydoc", "unittest", "PySide6.QtNetwork", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtOpenGL"],
    noarchive=False,
)
a.binaries = [b for b in a.binaries if wanted(b[0])]
a.datas = [d for d in a.datas if wanted(d[0])]
pyz = PYZ(a.pure)

if MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Clicker", console=False, upx=False,
              icon="assets/clicker.icns")
    coll = COLLECT(exe, a.binaries, a.datas, name="Clicker", upx=False)
    app = BUNDLE(coll, name="Clicker.app", icon="assets/clicker.icns", bundle_identifier="com.clicker.app")
elif WIN:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Clicker", console=False, upx=False,
              icon="assets/clicker.ico", version="build/version_info.txt")
    coll = COLLECT(exe, a.binaries, a.datas, name="Clicker", upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Clicker", console=False, upx=False)
