"""Build scheduler.exe with PyInstaller. Bakes the git version into the bundle.

    pip install -r requirements-dev.txt
    python build.py
"""
import os
import subprocess
import sys
from pathlib import Path

from scheduler.version import git_version

ROOT = Path(__file__).resolve().parent
VFILE = ROOT / "scheduler" / "_version.py"


def main():
    version = git_version(ROOT) or "dev"
    print("version:", version)
    VFILE.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    try:
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
            "--name", "scheduler",
            "--add-data", f"{ROOT / 'scheduler' / 'web'}{os.pathsep}scheduler/web",
            str(ROOT / "run.py"),
        ], cwd=ROOT, check=True)
    finally:
        VFILE.unlink(missing_ok=True)  # keep working tree clean so the next build isn't "dirty"


if __name__ == "__main__":
    main()
