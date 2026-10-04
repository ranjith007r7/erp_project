"""
Test doubles for the Unified Intelligence Layer.

FakeLLM is a SCRIPTED model: it returns exactly what a test tells it to. That
makes the whole pipeline deterministic and, more importantly, lets tests make
the "AI" behave MALICIOUSLY on purpose (return DROP TABLE, set_config, a query
against the users table, ...) to prove the safety layers hold. Relying on a
real model happening to misbehave would test nothing repeatably.
"""


class FakeLLM:
    def __init__(self, *, gate="YES", sql=None, phrase=None, rewrite=None, fail_on=None):
        self.calls_used = 0
        self.prompts = []
        self.kinds = []
        self._gate = gate
        self._sql = list(sql) if isinstance(sql, (list, tuple)) else [sql]
        self._phrase = phrase
        self._rewrite = rewrite
        self._fail_on = fail_on  # prompt kind that should raise LLMError

    @staticmethod
    def kind_of(prompt: str) -> str:
        if "Reply with exactly one word: YES or NO" in prompt:
            return "gate"
        if "Rewrite the user's latest message" in prompt:
            return "rewrite"
        if "You write PostgreSQL SELECT queries" in prompt:
            return "sql"
        if "Answer the question using ONLY the data below" in prompt:
            return "phrase"
        raise AssertionError("FakeLLM received a prompt it does not recognise")

    def generate(self, prompt, *, max_tokens=1024):
        from app.services.intelligence.llm import LLMError

        kind = self.kind_of(prompt)
        self.calls_used += 1
        self.prompts.append(prompt)
        self.kinds.append(kind)
        if self._fail_on == kind:
            raise LLMError("scripted model failure")
        if kind == "gate":
            return self._gate
        if kind == "rewrite":
            return self._rewrite or "a standalone question"
        if kind == "sql":
            return self._sql.pop(0) if len(self._sql) > 1 else self._sql[0]
        return self._phrase(prompt) if callable(self._phrase) else (self._phrase or "Here is the answer.")
