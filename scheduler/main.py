import faulthandler
import json
import platform
import sys
import tempfile
import threading
import time
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


WATCHDOG_SECONDS = 60  # cold WebView2 start can take a long time on slow machines
WEBVIEW2_KEY = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def message_box(text: str):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "My Scheduler", 0x10)


def webview2_version() -> str | None:
    """Installed WebView2 runtime version (None if not found or not on Windows)."""
    if sys.platform != "win32":
        return None
    import winreg
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + "\\" + WEBVIEW2_KEY),
                      (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + WEBVIEW2_KEY),
                      (winreg.HKEY_CURRENT_USER, "Software\\" + WEBVIEW2_KEY)):
        try:
            with winreg.OpenKey(hive, key) as k:
                return winreg.QueryValueEx(k, "pv")[0]
        except OSError:
            continue
    return None


class StartLog:
    """scheduler-start.log: one fresh file per run, next to the exe. A windowed exe has no console, so
    this is how we learn how far startup got on a machine where no window appears."""

    def __init__(self):
        for d in (app_dir(), Path(tempfile.gettempdir())):
            try:
                self.path = d / "scheduler-start.log"
                self.f = open(self.path, "w", encoding="utf-8", buffering=1)
                break
            except OSError:
                continue
        else:  # nowhere writable: keep going without a file
            self.path, self.f = None, None

    def __call__(self, msg: str):
        if self.f:
            self.f.write(time.strftime("%H:%M:%S") + " " + msg + "\n")


def report_error(exc_text: str) -> Path:
    """A windowed .exe has no console, so leave a log next to it and tell the user."""
    log = app_dir() / "scheduler-error.log"
    try:
        log.write_text(f"My Scheduler {get_version()}\n\n{exc_text}", encoding="utf-8")
    except OSError:  # e.g. the folder is read-only
        log = Path(tempfile.gettempdir()) / "scheduler-error.log"
        log.write_text(f"My Scheduler {get_version()}\n\n{exc_text}", encoding="utf-8")
    message_box(f"프로그램을 시작하지 못했습니다.\n\n{exc_text.strip().splitlines()[-1]}\n\n자세한 내용: {log}")
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
    log = StartLog()
    log(f"My Scheduler {get_version()}")
    log(f"python {platform.python_version()}  {platform.platform()}  frozen={bool(getattr(sys, 'frozen', False))}")
    log(f"exe: {sys.executable}")
    if sys.platform == "win32":
        log(f"WebView2 runtime: {webview2_version() or 'NOT FOUND (install the Evergreen runtime)'}")
    loaded = threading.Event()
    if log.f:
        faulthandler.enable(log.f)  # native crashes
        faulthandler.dump_traceback_later(WATCHDOG_SECONDS, file=log.f)  # stack of every thread if still not loaded
    threading.excepthook = lambda a: log("thread error: " + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))

    def watchdog():
        if not loaded.is_set():
            log(f"WATCHDOG: page not loaded after {WATCHDOG_SECONDS}s (thread stacks were dumped above)")
            message_box(f"창이 {WATCHDOG_SECONDS}초가 지나도록 아직 열리지 않았습니다. 느린 PC에서는 계속 로딩 중일 수 있습니다.\n\n자세한 내용: {log.path}")

    try:
        import webview  # imported lazily so tests don't need it

        log(f"pywebview {getattr(webview, '__version__', '?')}")
        api = Api(Store(connect()), log=log)
        log("db ready")
        window = webview.create_window(
            f"My Scheduler {get_version()}",
            str(web_dir() / "index.html"),
            js_api=api, width=1400, height=860,
        )
        window.events.shown += lambda: log("event: shown")

        def on_loaded():
            loaded.set()
            faulthandler.cancel_dump_traceback_later()
            log("event: loaded")
        window.events.loaded += on_loaded
        t = threading.Timer(WATCHDOG_SECONDS, watchdog)
        t.daemon = True
        t.start()
        log("webview.start")
        # Force WebView2 on Windows: pywebview would otherwise fall back to the old IE engine
        # (blank page) when the runtime is missing.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
        log("webview.start returned (window closed)")
    except Exception:
        log("EXCEPTION:\n" + traceback.format_exc())
        report_error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
