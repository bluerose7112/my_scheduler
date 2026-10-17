"""Browser-based dev server exposing the same Api (no pywebview needed).

    python -m scheduler.devserver [port]
"""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .api import Api
from .db import connect
from .store import Store

WEB = Path(__file__).resolve().parent / "web"


def make_handler(api: Api):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB), **kw)

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            fn = getattr(api, name, None) if not name.startswith("_") else None
            if not callable(fn):
                self.send_error(404)
                return
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "[]")
            body = json.dumps(fn(*args)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    return H


def serve(api: Api, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(api))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"http://127.0.0.1:{port}")
    serve(Api(Store(connect())), port).serve_forever()
