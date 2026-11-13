"""Optional local LLM enrichment through an Ollama-compatible endpoint.

Confidentiality controls:
  * Only loopback hosts are accepted unless LCC_ALLOW_REMOTE_LLM=1 is set explicitly.
  * Literals (strings, long numbers) can be masked before code leaves the analyzer.
  * Nothing is sent anywhere unless the user turns the LLM option on for a request.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class LLMConfigError(ValueError):
    pass


def mask_literals(code: str) -> tuple[str, int]:
    """Replace string literals and long digit runs with placeholders."""
    count = 0

    def s(m):
        nonlocal count
        count += 1
        q = m.group(0)[0]
        return f"{q}<STR{count}>{q}"

    def n(m):
        nonlocal count
        count += 1
        return f"<NUM{count}>"

    out = re.sub(r"'(?:[^'\n]|'')*'|\"[^\"\n]*\"", s, code)
    out = re.sub(r"(?<![\w-])\d{5,}(?![\w-])", n, out)
    return out, count


class LocalLLM:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 60.0):
        self.url = (url or os.environ.get("LCC_LLM_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.model = model or os.environ.get("LCC_LLM_MODEL") or ""
        self.timeout = timeout
        host = urlparse(self.url).hostname or ""
        if host not in LOOPBACK and os.environ.get("LCC_ALLOW_REMOTE_LLM") != "1":
            raise LLMConfigError(f"LLM host '{host}' is not local. Set LCC_ALLOW_REMOTE_LLM=1 only if the "
                                 "client's confidentiality agreement permits it.")
        self._status_cache: tuple[float, dict] | None = None

    def _req(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if data else "GET")
        # Never route through a corporate proxy: the endpoint is local by design.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def status(self) -> dict:
        now = time.time()
        if self._status_cache and now - self._status_cache[0] < 15:
            return self._status_cache[1]
        info = {"available": False, "url": self.url, "model": self.model, "models": []}
        try:
            tags = self._req("/api/tags", timeout=1.5)
            models = [m.get("name", "") for m in tags.get("models", [])]
            info["models"] = models
            if not self.model and models:
                self.model = models[0]
                info["model"] = self.model
            info["available"] = bool(models) and (self.model in models or any(m.startswith(self.model) for m in models))
            if not models:
                info["reason"] = "Ollama is running but has no models (run: ollama pull llama3.1:8b)"
        except (urllib.error.URLError, OSError, ValueError) as e:
            info["reason"] = f"No local LLM reachable at {self.url} ({type(e).__name__})"
        self._status_cache = (now, info)
        return info

    def complete(self, prompt: str, max_tokens: int = 220) -> str:
        res = self._req("/api/generate", {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        })
        text = res.get("response", "").strip()
        text = re.sub(r"^\s*(?:Summary|Explanation)\s*:\s*", "", text, flags=re.I)
        return " ".join(text.replace("**", "").split())


SUMMARY_PROMPT = """You document legacy {language} code for a modernization team (developers, analysts, project managers).
Write ONE or TWO plain sentences explaining the business purpose of the {kind} `{name}` below:
what it achieves, the key rule or calculation, and what it reads or changes. Do not restate syntax,
do not use markdown, do not invent facts that are not in the code.

Static-analysis facts (reliable): {facts}

```
{code}
```
Explanation:"""

EXPLAIN_PROMPT = """You are helping a developer new to {language} understand legacy code during a migration.
Explain what lines {start}-{end} do, in 2-4 plain sentences, including any business rule and anything
risky to preserve when rewriting it in a modern language. No markdown.

Context facts from static analysis: {facts}

```
{code}
```
Explanation:"""
