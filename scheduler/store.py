import json
import re
import sqlite3
from datetime import date

from .db import PRIORITIES, STATUSES, TYPES

FIELDS = (
    "title", "description", "status", "priority", "assignee", "reporter",
    "labels", "start_date", "due_date", "estimate_h", "progress",
)
CHILD_TYPE = {"project": "item", "item": "subitem"}
LINK_RE = re.compile(r"\[\[([A-Za-z0-9]+(?:-\d+)?)\]\]")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ValidationError(ValueError):
    pass


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in FIELDS:
            continue
        if k in ("start_date", "due_date"):
            v = (v or "").strip() or None
            if v is not None:
                if not _DATE_RE.match(v):
                    raise ValidationError(f"{k}: YYYY-MM-DD 형식이어야 합니다 ({v})")
                date.fromisoformat(v)
        elif k == "status" and v not in STATUSES:
            raise ValidationError(f"status: {STATUSES} 중 하나여야 합니다 ({v})")
        elif k == "priority" and v not in PRIORITIES:
            raise ValidationError(f"priority: {PRIORITIES} 중 하나여야 합니다 ({v})")
        elif k == "progress":
            v = max(0, min(100, int(v or 0)))
        elif k == "estimate_h":
            v = None if v in (None, "") else float(v)
        elif k == "labels" and isinstance(v, list):
            v = ",".join(str(x).strip() for x in v if str(x).strip())
        elif k == "title":
            v = (v or "").strip()
            if not v:
                raise ValidationError("title이 비어 있습니다")
        elif v is None:
            v = ""
        out[k] = v
    return out


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.db = conn

    # ---- reads -------------------------------------------------------
    def get(self, key_or_id) -> dict | None:
        col = "id" if isinstance(key_or_id, int) else "key"
        r = self.db.execute(f"SELECT * FROM issues WHERE {col}=?", (key_or_id,)).fetchone()
        return dict(r) if r else None

    def list_all(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM issues ORDER BY sort_order, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def tree(self) -> list[dict]:
        nodes = {r["id"]: {**r, "children": []} for r in self.list_all()}
        roots = []
        for n in nodes.values():
            p = nodes.get(n["parent_id"])
            (p["children"] if p else roots).append(n)
        return roots

    # ---- graph / retrieval (used by the LLM) --------------------------
    def search(self, query: str = "", status=None, assignee=None, type_=None,
               due_before=None, due_after=None, limit: int = 20) -> list[dict]:
        where, args = [], []
        for tok in (query or "").split():
            where.append("(key LIKE ? OR title LIKE ? OR description LIKE ? OR labels LIKE ? OR assignee LIKE ?)")
            args += [f"%{tok}%"] * 5
        for col, val in (("status", status), ("assignee", assignee), ("type", type_)):
            if val:
                where.append(f"{col}=?"); args.append(val)
        if due_before:
            where.append("due_date IS NOT NULL AND due_date<=?"); args.append(due_before)
        if due_after:
            where.append("due_date IS NOT NULL AND due_date>=?"); args.append(due_after)
        sql = "SELECT * FROM issues" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.db.execute(sql + " ORDER BY due_date IS NULL, due_date, id LIMIT ?", [*args, int(limit)])
        return [dict(r) for r in rows]

    def links_out(self, issue: dict) -> list[str]:
        """[[KEY]] references in title/description (Obsidian-style wiki links)."""
        found = LINK_RE.findall(issue["title"] + "\n" + issue["description"])
        return [k for k in dict.fromkeys(found) if k != issue["key"] and self.get(k)]

    def backlinks(self, key: str) -> list[str]:
        rows = self.db.execute("SELECT key FROM issues WHERE key<>? AND (description LIKE ? OR title LIKE ?)",
                               (key, f"%[[{key}]]%", f"%[[{key}]]%")).fetchall()
        return [r[0] for r in rows]

    def neighborhood(self, key: str) -> dict | None:
        row = self.get(key)
        if not row:
            return None
        parent = self.get(row["parent_id"]) if row["parent_id"] else None
        kids = self.db.execute("SELECT * FROM issues WHERE parent_id=? ORDER BY sort_order,id", (row["id"],)).fetchall()
        return {"issue": row, "parent": parent["key"] if parent else None,
                "children": [dict(k) for k in kids],
                "links": self.links_out(row), "backlinks": self.backlinks(key)}

    # ---- keys --------------------------------------------------------
    def _root_key(self, issue: dict) -> str:
        while issue["parent_id"] is not None:
            issue = self.get(issue["parent_id"])
        return issue["key"]

    def _next_key(self, type_: str, parent: dict | None, project_key: str | None) -> str:
        if type_ == "project":
            base = re.sub(r"[^A-Za-z0-9]", "", (project_key or "")).upper()
            if not base:
                n = self.db.execute("SELECT COUNT(*) FROM issues WHERE type='project'").fetchone()[0]
                base = f"P{n + 1}"
            key, i = base, 1
            while self.get(key):
                i += 1
                key = f"{base}{i}"
            return key
        root = self._root_key(parent)
        like = f"{root}-%"
        rows = self.db.execute("SELECT key FROM issues WHERE key LIKE ?", (like,)).fetchall()
        nums = [int(r[0].rsplit("-", 1)[1]) for r in rows if r[0].rsplit("-", 1)[1].isdigit()]
        return f"{root}-{max(nums, default=0) + 1}"

    # ---- writes ------------------------------------------------------
    def create(self, type_: str, title: str, parent: str | int | None = None,
               project_key: str | None = None, **fields) -> dict:
        if type_ not in TYPES:
            raise ValidationError(f"알 수 없는 type: {type_}")
        parent_row = None
        if type_ == "project":
            if parent is not None:
                raise ValidationError("project는 parent를 가질 수 없습니다")
        else:
            parent_row = self.get(parent) if parent is not None else None
            if not parent_row:
                raise ValidationError(f"{type_}의 parent를 찾을 수 없습니다: {parent}")
            if CHILD_TYPE[parent_row["type"]] != type_:
                raise ValidationError(f"{parent_row['type']} 아래에는 {CHILD_TYPE[parent_row['type']]}만 만들 수 있습니다")
        data = _clean({"title": title, **fields})
        key = self._next_key(type_, parent_row, project_key)
        order = self.db.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM issues").fetchone()[0]
        cols = ["type", "parent_id", "key", "sort_order", *data]
        vals = [type_, parent_row["id"] if parent_row else None, key, order, *data.values()]
        cur = self.db.execute(
            f"INSERT INTO issues ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, key_or_id, **fields) -> dict:
        row = self.get(key_or_id)
        if not row:
            raise ValidationError(f"항목을 찾을 수 없습니다: {key_or_id}")
        data = _clean(fields)
        if data:
            sets = ",".join(f"{k}=?" for k in data) + ",updated_at=datetime('now','localtime')"
            self.db.execute(f"UPDATE issues SET {sets} WHERE id=?", [*data.values(), row["id"]])
            self.db.commit()
        return self.get(row["id"])

    def delete(self, key_or_id) -> list[dict]:
        """Delete issue and descendants; returns deleted rows (for undo)."""
        row = self.get(key_or_id)
        if not row:
            raise ValidationError(f"항목을 찾을 수 없습니다: {key_or_id}")
        rows = self._subtree(row["id"])
        self.db.execute("DELETE FROM issues WHERE id=?", (row["id"],))
        self.db.commit()
        return rows

    def _subtree(self, root_id: int) -> list[dict]:
        rows = self.db.execute(
            """WITH RECURSIVE t(id) AS (SELECT ? UNION ALL
               SELECT i.id FROM issues i JOIN t ON i.parent_id=t.id)
               SELECT * FROM issues WHERE id IN t ORDER BY id""", (root_id,)).fetchall()
        return [dict(r) for r in rows]

    def _restore(self, rows: list[dict]):
        for r in rows:
            cols = list(r)
            self.db.execute(
                f"INSERT INTO issues ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                list(r.values()))
        self.db.commit()

    # ---- batch with undo (used by LLM) ------------------------------
    def apply_ops(self, ops: list[dict], label: str = "") -> dict:
        """Apply create/update ops atomically; log inverse ops for undo.

        create: {op, type, parent(key|ref|title), ref?, fields{...}, project_key?}
        update: {op, key, fields{...}}
        """
        inverse: list[dict] = []
        refs: dict[str, str] = {}
        results: list[str] = []
        try:
            for op in ops:
                kind = op.get("op")
                fields = dict(op.get("fields") or {})
                if kind == "create":
                    type_ = op.get("type")
                    parent = op.get("parent")
                    parent = refs.get(parent, parent) if parent else None
                    if parent is not None and not self.get(parent):
                        parent = self._find_by_title(parent) or parent
                    title = fields.pop("title", None) or op.get("title")
                    row = self.create(type_, title, parent=parent,
                                      project_key=op.get("project_key"), **fields)
                    if op.get("ref"):
                        refs[op["ref"]] = row["key"]
                    inverse.append({"op": "delete", "id": row["id"]})
                    results.append(f"생성 {row['key']} {row['title']}")
                elif kind == "update":
                    key = refs.get(op.get("key"), op.get("key"))
                    before = self.get(key)
                    if not before:
                        raise ValidationError(f"수정 대상 없음: {key}")
                    after = self.update(key, **fields)
                    changed = {k: before[k] for k in _clean(fields) if before[k] != after[k]}
                    inverse.append({"op": "update", "id": before["id"], "fields": changed})
                    results.append(f"수정 {after['key']} {', '.join(changed) or '(변경 없음)'}")
                else:
                    raise ValidationError(f"지원하지 않는 op: {kind}")
        except Exception:
            self._undo_ops(inverse)  # roll back partial batch
            raise
        if inverse:
            self.db.execute("INSERT INTO undo_log (batch,label) VALUES (?,?)",
                            (json.dumps(inverse), label))
            self.db.commit()
        return {"results": results}

    def _find_by_title(self, title: str) -> str | None:
        r = self.db.execute("SELECT key FROM issues WHERE title=? COLLATE NOCASE", (title,)).fetchone()
        return r[0] if r else None

    def _undo_ops(self, inverse: list[dict]):
        for op in reversed(inverse):
            if op["op"] == "delete":
                self.db.execute("DELETE FROM issues WHERE id=?", (op["id"],))
            elif op["op"] == "update" and op["fields"]:
                sets = ",".join(f"{k}=?" for k in op["fields"])
                self.db.execute(f"UPDATE issues SET {sets} WHERE id=?",
                                [*op["fields"].values(), op["id"]])
        self.db.commit()

    def undo_last(self) -> str | None:
        r = self.db.execute("SELECT id,batch,label FROM undo_log ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        self._undo_ops(json.loads(r["batch"]))
        self.db.execute("DELETE FROM undo_log WHERE id=?", (r["id"],))
        self.db.commit()
        return r["label"]

    # ---- settings ----------------------------------------------------
    def get_settings(self) -> dict:
        d = {"llm_base_url": "http://localhost:1234/v1", "llm_protocol": "openai",
             "llm_model": "", "llm_api_key": "", "llm_timeout": "120",
             # UI preferences (kept in the db: a webview's localStorage may not survive restarts)
             "ui_sidebar": "1", "ui_kanban": "1", "ui_sum_collapsed": "0", "ui_project": ""}
        d.update({r[0]: r[1] for r in self.db.execute("SELECT key,value FROM settings")})
        return d

    def set_settings(self, values: dict):
        for k, v in values.items():
            if k.startswith(("llm_", "ui_")):
                self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
        self.db.commit()
