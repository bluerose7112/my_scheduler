import json
import sys
import tempfile
import traceback
from pathlib import Path

from .api import Api
from .db import app_dir, connect
from .store import Store
from .version import get_version


def web_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):  # PyInstaller bundle
        return Path(sys._MEIPASS) / "scheduler" / "web"
    return Path(__file__).resolve().parent / "web"


def report_error(exc_text: str) -> Path:
    """A windowed .exe has no console, so leave a log next to it and tell the user."""
    log = app_dir() / "scheduler-error.log"
    try:
        log.write_text(f"My Scheduler {get_version()}\n\n{exc_text}", encoding="utf-8")
    except OSError:  # e.g. the folder is read-only
        log = Path(tempfile.gettempdir()) / "scheduler-error.log"
        log.write_text(f"My Scheduler {get_version()}\n\n{exc_text}", encoding="utf-8")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, f"프로그램을 시작하지 못했습니다.\n\n{exc_text.strip().splitlines()[-1]}\n\n자세한 내용: {log}",
            "My Scheduler", 0x10)
    return log


def self_test(out: Path) -> int:
    """Headless check of a built exe: bundled web files, db, api, and the GUI backend's imports."""
    res: dict = {"version": get_version(), "frozen": bool(getattr(sys, "frozen", False)), "ok": True}
    try:
        res["web_files"] = sorted(p.name for p in web_dir().iterdir())
        assert "index.html" in res["web_files"], "index.html missing from bundle"
        with tempfile.TemporaryDirectory() as d:
            conn = connect(Path(d) / "t.db")
            try:
                api = Api(Store(conn))
                api.create("project", "self-test")
                assert api.tree()["data"][0]["title"] == "self-test"
            finally:
                conn.close()  # Windows cannot delete the temp dir while the db file is open
        import webview  # noqa: F401  (pywebview itself)
        if sys.platform == "win32":
            import webview.platforms.edgechromium  # noqa: F401  (WebView2 backend + pythonnet)
            res["backend"] = "edgechromium importable"
    except Exception:
        res["ok"] = False
        res["error"] = traceback.format_exc()
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if res["ok"] else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(self_test(Path(sys.argv[2] if len(sys.argv) > 2 else app_dir() / "self-test.json")))
    try:
        import webview  # imported lazily so tests don't need it

        api = Api(Store(connect()))
        webview.create_window(
            f"My Scheduler {get_version()}",
            str(web_dir() / "index.html"),
            js_api=api, width=1400, height=860,
        )
        # Force WebView2 on Windows: pywebview would otherwise fall back to the old IE engine
        # (blank page) when the runtime is missing.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
    except Exception:
        report_error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
