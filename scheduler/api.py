"""Methods exposed to the web UI via pywebview's js_api."""
from . import llm
from .store import Store, ValidationError
from .version import get_version


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return {"ok": True, "data": fn(*a, **kw)}
        except (ValidationError, llm.LLMError) as e:
            return {"ok": False, "error": str(e)}
    inner.__name__ = fn.__name__
    return inner


class Api:
    def __init__(self, store: Store):
        self._s = store

    @_wrap
    def version(self):
        return get_version()

    @_wrap
    def tree(self):
        return self._s.tree()

    @_wrap
    def create(self, type_, title, parent=None, fields=None):
        return self._s.create(type_, title, parent=parent, **(fields or {}))

    @_wrap
    def update(self, key, fields):
        return self._s.update(key, **fields)

    @_wrap
    def delete(self, key):
        return [r["key"] for r in self._s.delete(key)]

    @_wrap
    def get_settings(self):
        return self._s.get_settings()

    @_wrap
    def save_settings(self, values):
        self._s.set_settings(values)
        return True

    @_wrap
    def test_llm(self):
        return llm.test_connection(self._s.get_settings())

    @_wrap
    def diagnose_llm(self):
        return llm.diagnose(self._s.get_settings())

    @_wrap
    def get_item(self, key):
        n = self._s.neighborhood(key)
        if not n:
            raise ValidationError(f"항목을 찾을 수 없습니다: {key}")
        return {"links": n["links"], "backlinks": n["backlinks"]}

    @_wrap
    def chat(self, text, history=None):
        r = llm.agent(self._s.get_settings(), self._s, text, history)
        applied = self._s.apply_ops(r["operations"], label=text[:80]) if r["operations"] else {"results": []}
        return {"answer": r["answer"], "results": applied["results"], "steps": r["steps"]}

    @_wrap
    def undo(self):
        return self._s.undo_last()
