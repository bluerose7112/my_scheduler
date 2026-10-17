import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scheduler import llm
from scheduler.api import Api
from scheduler.db import connect
from scheduler.store import Store, ValidationError
from scheduler.version import format_describe


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


def test_version_format():
    assert format_describe("v1.0.0-0-gabc1234") == "v1.0.0"
    assert format_describe("v1.0.0-3-gabc1234") == "v1.0.0(+3)"
    assert format_describe("v1.0.0-0-gabc1234-dirty") == "v1.0.0+"
    assert format_describe("v1.0.0-3-gabc1234-dirty") == "v1.0.0(+3)+"
    assert format_describe("abc1234-dirty") == "untagged-abc1234+"


def test_hierarchy_and_keys(store):
    p = store.create("project", "Alpha", project_key="al")
    i = store.create("item", "login", parent=p["key"], due_date="2026-10-30")
    s = store.create("subitem", "schema", parent=i["key"])
    assert (p["key"], i["key"], s["key"]) == ("AL", "AL-1", "AL-2")
    assert store.tree()[0]["children"][0]["children"][0]["key"] == "AL-2"
    with pytest.raises(ValidationError):
        store.create("subitem", "x", parent=p["key"])
    with pytest.raises(ValidationError):
        store.update(i["key"], due_date="10/30")


def test_delete_cascades(store):
    p = store.create("project", "A")
    i = store.create("item", "i", parent=p["key"])
    store.create("subitem", "s", parent=i["key"])
    assert len(store.delete(p["key"])) == 3
    assert store.list_all() == []


def test_apply_ops_and_undo(store):
    p = store.create("project", "A")
    res = store.apply_ops([
        {"op": "create", "type": "item", "ref": "x", "parent": "A", "fields": {"title": "login", "due_date": "2026-10-30"}},
        {"op": "create", "type": "subitem", "parent": "x", "fields": {"title": "schema"}},
        {"op": "update", "key": p["key"], "fields": {"status": "in_progress"}},
    ], label="t")
    assert len(res["results"]) == 3 and len(store.list_all()) == 3
    assert store.get(p["key"])["status"] == "in_progress"
    assert store.undo_last() == "t"
    assert len(store.list_all()) == 1 and store.get(p["key"])["status"] == "todo"


def test_apply_ops_atomic(store):
    store.create("project", "A")
    with pytest.raises(ValidationError):
        store.apply_ops([
            {"op": "create", "type": "item", "parent": "A", "fields": {"title": "ok"}},
            {"op": "create", "type": "item", "parent": "A", "fields": {"title": "bad", "status": "nope"}},
        ])
    assert len(store.list_all()) == 1


def test_parse_reply():
    r = llm.parse_reply('<think>hm</think>```json\n{"operations": [], "message": "m"}\n```')
    assert r["message"] == "m"
    with pytest.raises(llm.LLMError):
        llm.parse_reply("no json")


def test_llm_end_to_end(store):
    reply = {"message": "ok", "operations": [
        {"op": "create", "type": "project", "ref": "p", "fields": {"title": "A과제"}},
        {"op": "create", "type": "item", "parent": "p", "fields": {"title": "로그인 API", "due_date": "2026-10-30"}},
    ]}
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
            self.wfile.write(out)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = Api(store)
    api.save_settings({"llm_base_url": f"http://127.0.0.1:{srv.server_port}/v1"})
    r = api.llm_input("다음주 금요일까지 A과제에 로그인 API")
    srv.shutdown()
    assert r["ok"], r
    assert seen["path"] == "/v1/chat/completions"
    assert "A과제" not in seen["body"]["messages"][0]["content"]  # nothing existing yet
    assert [x["title"] for x in store.list_all()] == ["A과제", "로그인 API"]
