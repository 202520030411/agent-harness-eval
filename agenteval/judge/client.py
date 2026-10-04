"""判官模型调用：OpenAI 兼容 chat/completions，标准库实现，磁盘缓存按 (model, prompt_hash)。"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CACHE = Path(os.environ.get("AGENTEVAL_JUDGE_CACHE", "~/.cache/agenteval/judge")).expanduser()


class JudgeClient:
    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY", base_url: str = "https://api.openai.com/v1",
                 cache_dir: Path = DEFAULT_CACHE, temperature: float | None = None, reasoning_effort: str | None = "medium",
                 max_tokens: int = 2000, provider: str | None = None):
        self.model, self.base_url = model, base_url.rstrip("/")
        self.provider = provider or ("anthropic" if model.startswith("claude") else "openai")
        if self.provider == "anthropic":
            if api_key_env == "OPENAI_API_KEY": api_key_env = "ANTHROPIC_API_KEY"
            if base_url == "https://api.openai.com/v1": self.base_url = "https://api.anthropic.com/v1"
        self.key = os.environ.get(api_key_env)
        if not self.key:
            raise RuntimeError(f"{api_key_env} not set")
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.temperature, self.reasoning_effort, self.max_tokens = temperature, reasoning_effort, max_tokens
        self.calls = 0; self.cache_hits = 0; self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _key(self, system: str, user: str) -> str:
        return hashlib.sha256(json.dumps([self.model, system, user, self.temperature, self.reasoning_effort]).encode()).hexdigest()

    def complete(self, system: str, user: str, use_cache: bool = True) -> str:
        k = self._key(system, user); f = self.cache_dir / f"{k}.json"
        if use_cache and f.exists():
            self.cache_hits += 1
            return json.loads(f.read_text())["content"]
        if self.provider == "anthropic":
            # claude 默认带思考：max_tokens 太小会全花在 thinking 上、正文为空（2026-09-24 踩坑：2000 全是 thinking_tokens）。
            # Claude 5 系列用 thinking.type=adaptive + output_config.effort 控制，给正文之外再留 8k 给思考。
            body = {"model": self.model, "system": system, "messages": [{"role": "user", "content": user}],
                    "max_tokens": max(self.max_tokens, 4000) + 24000}   # 全 context 输入下 adaptive thinking 会用掉 >12k（2026-09-25 踩坑）
            if self.reasoning_effort and self.reasoning_effort != "none":
                body["thinking"] = {"type": "adaptive"}; body["output_config"] = {"effort": self.reasoning_effort}
            elif self.temperature is not None:
                body["temperature"] = self.temperature
            req = urllib.request.Request(f"{self.base_url}/messages", data=json.dumps(body).encode(),
                                         headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        else:
            body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "max_completion_tokens": self.max_tokens}
            if self.temperature is not None: body["temperature"] = self.temperature
            if self.reasoning_effort: body["reasoning_effort"] = self.reasoning_effort
            req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        last = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:300]!r}"
                if e.code in (429, 500, 502, 503, 504): time.sleep(5 * (attempt + 1)); continue
                raise RuntimeError(last)
            except Exception as e:  # 网络抖动
                last = repr(e); time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"judge call failed after retries: {last}")
        self.calls += 1
        u = data.get("usage") or {}
        if self.provider == "anthropic":
            self.usage["prompt_tokens"] += u.get("input_tokens", 0); self.usage["completion_tokens"] += u.get("output_tokens", 0)
            content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            if not content.strip():
                raise RuntimeError(f"anthropic returned no text (stop_reason={data.get('stop_reason')}, usage={u})")
        else:
            self.usage["prompt_tokens"] += u.get("prompt_tokens", 0); self.usage["completion_tokens"] += u.get("completion_tokens", 0)
            content = data["choices"][0]["message"]["content"] or ""
        f.write_text(json.dumps({"model": data.get("model"), "content": content, "usage": u}))
        return content
