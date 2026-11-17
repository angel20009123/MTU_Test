"""Build a versioned Windows executable, including native version resources."""
from pathlib import Path
import re
import subprocess
import sys
from version import VERSION

ROOT = Path(__file__).resolve().parent


def build():
    if not re.fullmatch(r"\d+\.\d+\.\d+", VERSION):
        raise ValueError("Invalid VERSION")
    numbers = tuple(map(int, VERSION.split("."))) + (0,)
    directory = ROOT / "build"
    directory.mkdir(exist_ok=True)
    resource = directory / "windows_version.txt"
    resource.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'Link Lab - MTU and Packet Tester'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('ProductName', 'MTU Link Tester'),
    StringStruct('ProductVersion', '{VERSION}'),
    StringStruct('OriginalFilename', 'MTU_Link_Tester_v{VERSION}.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)''', encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--icon", "assets/link_lab.ico",
        "--add-data", "assets/link_lab.ico;assets", "--version-file", str(resource),
        "--name", f"MTU_Link_Tester_v{VERSION}", "app.py"], cwd=ROOT, check=True)
    output = ROOT / "dist" / f"MTU_Link_Tester_v{VERSION}.exe"
    print(f"EXE: {output}")
    return output


if __name__ == "__main__":
    build()
