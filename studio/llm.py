"""Провайдеры LLM для творческого планирования.

- Anthropic (официальный SDK `anthropic`, модель по умолчанию claude-opus-5-5,
  адаптивное мышление, серверный fallback при отказе классификатора).
- Ollama (локально, бесплатно; качество ниже, но для проверки пайплайна хватает).

Единый контракт: `complete_json(system, user) -> dict`. Ответ всегда разбирается
как JSON с восстановлением (срез ```json-ограждений, поиск первого объекта).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Protocol

ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str, max_tokens: int = 16000) -> dict: ...

    def complete_text(self, system: str, user: str, max_tokens: int = 4000) -> str: ...


def extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели, терпимо к обрамлению."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    if not t.startswith("{"):
        start = t.find("{")
        if start < 0:
            raise LLMError("в ответе модели нет JSON-объекта:\n" + text[:500])
        t = t[start:]
    # обрезаем хвост после последней закрывающей скобки
    end = t.rfind("}")
    if end > 0:
        t = t[: end + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # частые огрехи: висящие запятые, одинарные кавычки у ключей
        fixed = re.sub(r",\s*([}\]])", r"\1", t)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            raise LLMError(f"модель вернула невалидный JSON ({e}):\n{text[:800]}") from e


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, model: str = "", effort: str = "high", api_key: str | None = None):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise LLMError("не установлен пакет anthropic: .venv/bin/pip install anthropic") from e
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model or ANTHROPIC_DEFAULT_MODEL
        self.effort = effort if effort in ("low", "medium", "high", "xhigh", "max") else "high"
        self.last_usage: dict = {}

    def _stream(self, system: str, user: str, max_tokens: int):
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}],
                      thinking={"type": "adaptive"}, output_config={"effort": self.effort})
        try:
            with self.client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                                  **kwargs) as stream:
                return stream.get_final_message()
        except self._anthropic.BadRequestError as e:
            # fallbacks/thinking недоступны для этой модели или аккаунта — повторяем без них
            if "fallback" in str(e).lower() or "thinking" in str(e).lower():
                kwargs.pop("thinking", None)
                with self.client.messages.stream(**kwargs) as stream:
                    return stream.get_final_message()
            raise

    def _call(self, system: str, user: str, max_tokens: int) -> str:
        a = self._anthropic
        for attempt in range(3):
            try:
                msg = self._stream(system, user, max_tokens)
                break
            except a.RateLimitError as e:
                wait = int(getattr(e, "response", None) and e.response.headers.get("retry-after", "20") or 20)
                time.sleep(min(wait, 60))
            except a.APIStatusError as e:
                if e.status_code >= 500 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise LLMError(f"Anthropic API: {e.status_code} {e.message}") from e
            except a.APIConnectionError as e:
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise LLMError("нет связи с Anthropic API") from e
        else:
            raise LLMError("Anthropic API: исчерпаны попытки")
        if msg.stop_reason == "refusal":
            det = getattr(msg, "stop_details", None)
            raise LLMError(f"модель отказалась выполнять запрос ({getattr(det, 'category', '?')}): "
                           f"{getattr(det, 'explanation', '')}")
        if msg.stop_reason == "max_tokens":
            raise LLMError("ответ модели обрезан по max_tokens — уменьшите объём (меньше сцен за вызов)")
        u = msg.usage
        self.last_usage = {"input": u.input_tokens, "output": u.output_tokens, "model": msg.model}
        return "".join(b.text for b in msg.content if b.type == "text")

    def complete_text(self, system: str, user: str, max_tokens: int = 4000) -> str:
        return self._call(system, user, max_tokens)

    def complete_json(self, system: str, user: str, max_tokens: int = 16000) -> dict:
        sys_json = system + "\n\nRespond with a single valid JSON object and nothing else: no prose, no markdown fences."
        text = self._call(sys_json, user, max_tokens)
        try:
            return extract_json(text)
        except LLMError:
            repair = self._call("You fix broken JSON. Return only the corrected JSON object.", text, max_tokens)
            return extract_json(repair)


class OllamaLLM:
    name = "ollama"

    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen3:8b", num_ctx: int = 16384):
        self.url, self.model, self.num_ctx = url.rstrip("/"), model, num_ctx
        self.last_usage: dict = {}

    def _chat(self, system: str, user: str, max_tokens: int, json_mode: bool) -> str:
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"num_ctx": self.num_ctx, "num_predict": max_tokens, "temperature": 0.7}}
        if json_mode:
            body["format"] = "json"
        req = urllib.request.Request(self.url + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                res = json.loads(r.read().decode())
        except urllib.error.URLError as e:
            raise LLMError(f"Ollama недоступна по адресу {self.url}: {e}. Запустите `ollama serve` "
                           f"или настройте провайдера anthropic") from e
        self.last_usage = {"input": res.get("prompt_eval_count"), "output": res.get("eval_count"), "model": self.model}
        return res["message"]["content"]

    def complete_text(self, system: str, user: str, max_tokens: int = 4000) -> str:
        return self._chat(system, user, max_tokens, json_mode=False)

    def complete_json(self, system: str, user: str, max_tokens: int = 16000) -> dict:
        text = self._chat(system + "\n\nRespond with one valid JSON object only.", user, max_tokens, json_mode=True)
        return extract_json(text)


class FakeLLM:
    """Для тестов: отдаёт заранее заготовленные ответы по очереди или через функцию."""
    name = "fake"

    def __init__(self, responses=None, handler=None):
        self.responses = list(responses or [])
        self.handler = handler
        self.calls: list[tuple[str, str]] = []
        self.last_usage = {}

    def complete_json(self, system: str, user: str, max_tokens: int = 16000) -> dict:
        self.calls.append((system, user))
        if self.handler:
            return self.handler(system, user)
        if not self.responses:
            raise LLMError("FakeLLM: ответы закончились")
        r = self.responses.pop(0)
        return r if isinstance(r, dict) else extract_json(r)

    def complete_text(self, system: str, user: str, max_tokens: int = 4000) -> str:
        self.calls.append((system, user))
        r = self.handler(system, user) if self.handler else self.responses.pop(0)
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


def make_llm(cfg: dict) -> LLM:
    llm_cfg = cfg.get("llm", {})
    provider = str(llm_cfg.get("provider", "auto")).lower()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                   or cfg.get("anthropic_api_key"))
    if provider == "auto":
        provider = "anthropic" if has_key else "ollama"
    if provider == "anthropic":
        return AnthropicLLM(model=llm_cfg.get("model", ""), effort=llm_cfg.get("effort", "high"),
                            api_key=cfg.get("anthropic_api_key") or None)
    if provider == "ollama":
        return OllamaLLM(url=llm_cfg.get("ollama_url", "http://localhost:11434"),
                         model=llm_cfg.get("model") or llm_cfg.get("ollama_model", "qwen3:8b"))
    raise LLMError(f"неизвестный провайдер LLM: {provider}")
