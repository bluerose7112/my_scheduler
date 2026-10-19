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
    p = store.create("project", "A", project_key="A")
    i = store.create("item", "i", parent=p["key"])
    store.create("subitem", "s", parent=i["key"])
    assert len(store.delete(p["key"])) == 3
    assert store.list_all() == []


def test_apply_ops_and_undo(store):
    p = store.create("project", "A", project_key="A")
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
    store.create("project", "A", project_key="A")
    with pytest.raises(ValidationError):
        store.apply_ops([
            {"op": "create", "type": "item", "parent": "A", "fields": {"title": "ok"}},
            {"op": "create", "type": "item", "parent": "A", "fields": {"title": "bad", "status": "nope"}},
        ])
    assert len(store.list_all()) == 1


def test_parse_reply():
    r = llm.parse_json('<think>hm</think>```json\n{"operations": [], "message": "m"}\n```')
    assert r["message"] == "m"
    with pytest.raises(llm.LLMError):
        llm.parse_json("no json")


def test_search_links_outline(store):
    p = store.create("project", "A", project_key="A")
    i = store.create("item", "login", parent="A", assignee="kim", due_date="2026-10-30")
    j = store.create("item", "deploy", parent="A", description="after [[A-1]] and [[NOPE-9]]")
    assert [r["key"] for r in store.search("log")] == ["A-1"]
    assert [r["key"] for r in store.search(assignee="kim", due_before="2026-11-01")] == ["A-1"]
    n = store.neighborhood("A-2")
    assert n["links"] == ["A-1"] and store.neighborhood("A-1")["backlinks"] == ["A-2"]
    out = llm.build_outline(store.list_all())
    assert "A-1 [i] login" in out and "  A-1" in out
    big = [{**r, "id": r["id"] + k * 100, "parent_id": None, "key": f"K{k}", "title": "x" * 50, "status": "done"}
           for k in range(300) for r in [i]]
    assert len(llm.build_outline(big)) < 7000


def test_agent_tool_loop_and_ops(store):
    store.create("project", "A", project_key="A")
    store.create("item", "login", parent="A", due_date="2026-10-30")
    script = iter([
        '{"tool":"search","args":{"query":"login"}}',
        '{"tool":"get","args":{"key":"A-1"}}',
        '```json\n{"answer":"done [A-1]","operations":[{"op":"update","key":"A-1","fields":{"status":"done"}}]}\n```',
    ])
    seen = []
    def fake(settings, msgs):
        seen.append(msgs[-1]["content"])
        return next(script)
    api = Api(store)
    import scheduler.llm as L
    orig, L.chat = L.chat, fake
    try:
        r = api.chat("로그인 완료 처리하고 설명해줘")
    finally:
        L.chat = orig
    assert r["ok"], r
    assert [s["tool"] for s in r["data"]["steps"]] == ["search", "get"]
    assert seen[1].startswith("TOOL_RESULT") and '"A-1"' in seen[1]
    assert store.get("A-1")["status"] == "done" and r["data"]["results"]
    assert api.undo()["ok"] and store.get("A-1")["status"] == "todo"


def test_llm_http(store):
    reply = {"answer": "ok", "operations": [
        {"op": "create", "type": "project", "ref": "p", "fields": {"title": "A과제"}}]}
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
    r = api.chat("A과제 만들어줘", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])
    srv.shutdown()
    assert r["ok"], r
    assert seen["path"] == "/v1/chat/completions"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user", "assistant", "user"]
    assert [x["title"] for x in store.list_all()] == ["A과제"]


def test_diagnose_non_ollama_server(store):
    """Plain OpenAI-compatible server: no /api/*, falls back to /v1/models and still runs the test call."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, out = (200, {"data": [{"id": "m1"}]}) if self.path == "/v1/models" else (404, {})
            self._send(code, out)
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self._send(200, {"choices": [{"message": {"content": '{"answer":"ok","operations":[]}'}}]})
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = llm.diagnose({"llm_base_url": f"http://127.0.0.1:{srv.server_port}/v1", "llm_model": "m1"})
    srv.shutdown()
    assert d["ollama"] is False and d["models"] == ["m1"]
    assert d["test"]["json_ok"] is True and d["request_params"] == {"temperature": 0}


def test_ui_settings_roundtrip(store):
    assert store.get_settings()["ui_sidebar"] == "1"
    store.set_settings({"ui_sidebar": "0", "ui_project": "P1", "evil": "x"})
    s = store.get_settings()
    assert s["ui_sidebar"] == "0" and s["ui_project"] == "P1" and "evil" not in s
