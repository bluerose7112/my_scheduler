"""Local LLM client. Only locally hosted servers; protocol is user-configured."""
import json
import re
import urllib.error
import urllib.request
from datetime import date

from .db import PRIORITIES, STATUSES

PROTOCOLS = ("openai",)  # OpenAI-compatible /chat/completions (LM Studio, llama.cpp, vLLM, Ollama /v1)

SYSTEM = """You are the scheduling assistant inside a Jira-like planner (think "Cursor, but for schedules").
Hierarchy: project(과제) > item > subitem. Items normally carry due dates. Issues may reference each other with [[KEY]] links in description/title.
Today is {today} ({weekday}). Resolve relative dates to YYYY-MM-DD. Reply in the user's language.
Values: status={statuses}; priority={priorities}.
Fields: title, description, status, priority, assignee, reporter, labels, start_date, due_date, estimate_h, progress(0-100).

You see only a compact OUTLINE below. To read details, call tools. Every reply must be exactly ONE JSON object, no prose:
 1) Tool call:  {{"tool":"search","args":{{"query":"words","status":"","assignee":"","type":"","due_before":"YYYY-MM-DD","due_after":"YYYY-MM-DD"}}}}   (all args optional; lists matches)
                {{"tool":"get","args":{{"key":"KEY"}}}}   (full fields + parent, children, [[links]], backlinks)
 2) Final reply: {{"answer":"text for the user (cite issues as [KEY])","operations":[...]}}
    operations (may be empty; applied immediately, so only edit when the user asks to):
      {{"op":"create","type":"project|item|subitem","ref":"optional-local-name","parent":"existing KEY or earlier ref","fields":{{"title":"..",...}}}}
      {{"op":"update","key":"EXISTING-KEY","fields":{{only changed fields}}}}
Rules: never invent keys; look things up with tools before answering questions you cannot answer from the outline; reuse existing projects/items instead of duplicating; an item's parent is a project, a subitem's parent is an item.

OUTLINE (key [type] title | status | due):
{outline}"""

MAX_STEPS = 6
OUTLINE_BUDGET = 6000  # chars; bigger data sets are trimmed and reached via tools


def _line(r: dict, depth: int) -> str:
    return f'{"  " * depth}{r["key"]} [{r["type"][0]}] {r["title"][:60]} | {r["status"]} | {r["due_date"] or "-"}'


def build_outline(rows: list[dict], budget: int = OUTLINE_BUDGET) -> str:
    if not rows:
        return "(empty)"
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(r)

    def render(skip) -> str:
        out = []
        def walk(pid, d):
            for r in by_parent.get(pid, []):
                if not skip(r):
                    out.append(_line(r, d)); walk(r["id"], d + 1)
        walk(None, 0)
        return "\n".join(out)

    for note, skip in (("", lambda r: False),
                       ("(trimmed: done items hidden; use search)", lambda r: r["status"] == "done"),
                       ("(trimmed: subitems & done hidden; use search)", lambda r: r["status"] == "done" or r["type"] == "subitem")):
        text = render(skip)
        if len(text) <= budget:
            return text + ("\n" + note if note else "")
    return text[:budget] + "\n(trimmed; use search)"


def build_messages(text: str, rows: list[dict], history: list[dict] | None = None,
                   today: date | None = None) -> list[dict]:
    today = today or date.today()
    system = SYSTEM.format(
        today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
        statuses="|".join(STATUSES), priorities="|".join(PRIORITIES), outline=build_outline(rows))
    hist = [{"role": h["role"], "content": str(h["content"])} for h in (history or [])[-10:]
            if h.get("role") in ("user", "assistant") and h.get("content")]
    return [{"role": "system", "content": system}, *hist, {"role": "user", "content": text}]


def _compact(r: dict) -> dict:
    keep = ("key", "type", "title", "status", "priority", "assignee", "start_date", "due_date", "progress", "labels")
    return {k: r[k] for k in keep if r.get(k) not in (None, "")}


def run_tool(store, name: str, args: dict) -> object:
    if name == "search":
        rows = store.search(args.get("query", ""), args.get("status") or None, args.get("assignee") or None,
                            args.get("type") or None, args.get("due_before") or None, args.get("due_after") or None)
        return {"count": len(rows), "results": [_compact(r) for r in rows]}
    if name == "get":
        n = store.neighborhood(str(args.get("key", "")))
        if not n:
            return {"error": f"no such key: {args.get('key')}"}
        return {"issue": {k: v for k, v in n["issue"].items() if v not in (None, "") and k not in ("id", "parent_id", "sort_order")},
                "parent": n["parent"], "children": [_compact(c) for c in n["children"]],
                "links": n["links"], "backlinks": n["backlinks"]}
    return {"error": f"unknown tool: {name}"}


def agent(settings: dict, store, text: str, history: list[dict] | None = None, chat_fn=None) -> dict:
    """Tool-calling loop over plain JSON (works with any local model, no native function calling needed)."""
    chat_fn = chat_fn or chat
    msgs = build_messages(text, store.list_all(), history)
    steps = []
    for _ in range(MAX_STEPS):
        raw = chat_fn(settings, msgs)
        try:
            obj = parse_json(raw)
        except LLMError:
            if len(msgs) and msgs[-1].get("_nudged"):
                raise
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Reply with exactly one JSON object as specified.", "_nudged": True}]
            continue
        if "tool" in obj:
            args = obj.get("args") or {}
            result = run_tool(store, obj["tool"], args)
            steps.append({"tool": obj["tool"], "args": args})
            msgs += [{"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)},
                     {"role": "user", "content": "TOOL_RESULT: " + json.dumps(result, ensure_ascii=False)}]
            continue
        ops = obj.get("operations") or []
        if not isinstance(ops, list):
            raise LLMError("operations must be a list")
        return {"answer": str(obj.get("answer") or obj.get("message") or ""), "operations": ops, "steps": steps}
    raise LLMError("LLM이 정해진 단계 안에 답을 끝내지 못했습니다")


WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


class LLMError(RuntimeError):
    pass


def chat(settings: dict, messages: list[dict]) -> str:
    proto = settings.get("llm_protocol", "openai")
    if proto not in PROTOCOLS:
        raise LLMError(f"지원하지 않는 프로토콜: {proto}")
    base = settings["llm_base_url"].rstrip("/")
    messages = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
    body = {"messages": messages, "temperature": 0}
    if settings.get("llm_model"):
        body["model"] = settings["llm_model"]
    headers = {"Content-Type": "application/json"}
    if settings.get("llm_api_key"):
        headers["Authorization"] = "Bearer " + settings["llm_api_key"]
    req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=float(settings.get("llm_timeout") or 120)) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"LLM 서버 오류 {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"LLM 서버에 연결할 수 없습니다 ({base}): {e}") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMError(f"예상하지 못한 응답 형식: {e}") from e


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise LLMError("LLM 응답에서 JSON을 찾지 못했습니다: " + text[:200])
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON 파싱 실패: {e}") from e
    if not isinstance(obj, dict):
        raise LLMError("JSON 객체가 아닙니다")
    return obj


def test_connection(settings: dict) -> str:
    return chat(settings, [{"role": "user", "content": "Reply with: ok"}])[:200]
