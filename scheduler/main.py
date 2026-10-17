import sys
from pathlib import Path

from .api import Api
from .db import connect
from .store import Store
from .version import get_version


def web_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):  # PyInstaller bundle
        return Path(sys._MEIPASS) / "scheduler" / "web"
    return Path(__file__).resolve().parent / "web"


def main():
    import webview  # imported lazily so tests don't need it

    api = Api(Store(connect()))
    webview.create_window(
        f"My Scheduler {get_version()}",
        str(web_dir() / "index.html"),
        js_api=api, width=1400, height=860,
    )
    webview.start()


if __name__ == "__main__":
    main()
