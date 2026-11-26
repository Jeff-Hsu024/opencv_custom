"""Install Google Android SDK Platform-Tools into the ignored project directory."""
import argparse
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://dl.google.com/android/repository/"
ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}

def install(root: Path = ROOT, force: bool = False) -> Path:
    system = platform.system()
    if system not in SYSTEMS:
        raise RuntimeError(f"Unsupported OS: {system}")
    dest = root / "platform-tools"
    name = "adb.exe" if system == "Windows" else "adb"
    if (dest / name).is_file() and not force:
        return dest / name
    url = BASE + f"platform-tools-latest-{SYSTEMS[system]}.zip"
    with tempfile.TemporaryDirectory(dir=root) as temp:
        tmp = Path(temp)
        archive = tmp / "platform-tools.zip"
        print(f"Downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                target = (tmp / entry.filename).resolve()
                if not target.is_relative_to(tmp.resolve()):
                    raise RuntimeError("Unsafe archive path")
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise RuntimeError("Unexpected archive symlink")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if system != "Windows":
                        mode = (entry.external_attr >> 16) & 0o777
                        if mode:
                            target.chmod(mode)
        staged = tmp / "platform-tools"
        adb = staged / name
        subprocess.run([str(adb), "version"], check=True)
        if dest.exists():
            previous = tmp / "previous"
            dest.rename(previous)
            try:
                staged.rename(dest)
            except BaseException:
                previous.rename(dest)
                raise
        else:
            staged.rename(dest)
    return dest / name

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Refresh an existing installation")
    args = parser.parse_args()
    print(install(force=args.force))
