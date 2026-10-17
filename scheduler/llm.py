"""Local LLM client. Only locally hosted servers; protocol is user-configured."""
import json
import re
import urllib.error
import urllib.request
from datetime import date

from .db import PRIORITIES, STATUSES

PROTOCOLS = ("openai",)  # OpenAI-compatible /chat/completions (LM Studio, llama.cpp, vLLM, Ollama /v1)

SYSTEM = """You convert the user's natural-language schedule notes into JSON edit operations.
Hierarchy: project (과제) > item > subitem. Only items normally carry due dates.
Today is {today} ({weekday}). Resolve relative dates ("다음주 금요일") to YYYY-MM-DD.
Allowed values: status={statuses}; priority={priorities}.
Fields: title, description, status, priority, assignee, reporter, labels, start_date, due_date, estimate_h, progress(0-100).
Reply with ONLY one JSON object, no prose:
{{"message": "short summary in the user's language",
  "operations": [
    {{"op":"create","type":"project|item|subitem","ref":"optional-local-name","parent":"existing KEY, project title, or earlier ref","fields":{{...}}}},
    {{"op":"update","key":"EXISTING-KEY","fields":{{only changed fields}}}}
  ]}}
Rules: use existing projects/items from the context instead of duplicating them; item's parent is a project, subitem's parent is an item; never invent keys for update.
Existing data:
{context}"""

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


class LLMError(RuntimeError):
    pass


def build_context(rows: list[dict]) -> str:
    if not rows:
        return "(none)"
    lines = []
    for r in rows:
        due = r["due_date"] or "-"
        lines.append(f'{r["key"]} [{r["type"]}] "{r["title"]}" status={r["status"]} due={due} parent={next((p["key"] for p in rows if p["id"] == r["parent_id"]), "-")}')
    return "\n".join(lines)


def build_messages(text: str, rows: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    system = SYSTEM.format(
        today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
        statuses="|".join(STATUSES), priorities="|".join(PRIORITIES),
        context=build_context(rows))
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def chat(settings: dict, messages: list[dict]) -> str:
    proto = settings.get("llm_protocol", "openai")
    if proto not in PROTOCOLS:
        raise LLMError(f"지원하지 않는 프로토콜: {proto}")
    base = settings["llm_base_url"].rstrip("/")
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


def parse_reply(text: str) -> dict:
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
    if not isinstance(obj.get("operations"), list):
        raise LLMError("응답에 operations 배열이 없습니다")
    return obj


def test_connection(settings: dict) -> str:
    return chat(settings, [{"role": "user", "content": "Reply with: ok"}])[:200]
