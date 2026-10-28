from __future__ import annotations

import math
import re


class TextBudgetCounter:
    """Counts and truncates text for prompt budget control.

    The default mode keeps the project's original character-count behavior.
    The "deepseek" mode is a local tokenizer-style estimate for OpenAI-compatible
    chat models. It does not call any remote API and does not require an API key.
    """

    def __init__(self, mode: str = "char"):
        self.mode = (mode or "char").strip().lower()

    def count(self, text: str) -> int:
        text = text or ""
        if self.mode in {"char", "chars", "character"}:
            return len(text)
        return sum(self._token_cost(token) for token in self._tokens(text))

    def take_head(self, text: str, limit: int) -> str:
        return self._take(text or "", limit, from_tail=False)

    def take_tail(self, text: str, limit: int) -> str:
        return self._take(text or "", limit, from_tail=True)

    def _take(self, text: str, limit: int, *, from_tail: bool) -> str:
        if limit <= 0 or not text:
            return ""
        if self.mode in {"char", "chars", "character"}:
            return text[-limit:] if from_tail else text[:limit]
        selected = []
        used = 0
        iterable = reversed(text) if from_tail else iter(text)
        for char in iterable:
            cost = self._char_cost(char)
            if used + cost > limit:
                break
            selected.append(char)
            used += cost
        if from_tail:
            selected.reverse()
        return "".join(selected)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]|[^\s]", text)

    def _char_cost(self, char: str) -> int:
        if not char.strip():
            return 0
        if "\u4e00" <= char <= "\u9fff":
            return 1
        if char.isascii() and char.isalnum():
            return 1
        return 1

    @staticmethod
    def _token_cost(token: str) -> int:
        if not token:
            return 0
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            return 1
        if re.fullmatch(r"[a-zA-Z0-9_]+", token):
            return max(1, math.ceil(len(token) / 4))
        return 1
