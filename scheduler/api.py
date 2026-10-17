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
    def llm_input(self, text):
        raw = llm.chat(self._s.get_settings(), llm.build_messages(text, self._s.list_all()))
        plan = llm.parse_reply(raw)
        res = self._s.apply_ops(plan["operations"], label=text[:80])
        return {"message": plan.get("message", ""), **res}

    @_wrap
    def undo(self):
        return self._s.undo_last()
