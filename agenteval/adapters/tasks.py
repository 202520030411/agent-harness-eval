"""题目文本查找：Harbor 缓存里每题一个目录（哈希名），task.toml 的 task.name 给出真名。"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def task_index(root: str) -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for toml in Path(root).rglob("task.toml"):
        try:
            name = tomllib.loads(toml.read_text())["task"]["name"].split("/")[-1]
        except Exception:
            continue
        idx[name] = toml.parent
    return idx


def instruction_for(task_name: str, root: str = "/root/.cache/harbor") -> str | None:
    d = task_index(root).get(task_name)
    if not d:
        return None
    f = d / "instruction.md"
    return f.read_text() if f.exists() else None


def tests_for(task_name: str, root: str = "/root/.cache/harbor", max_chars: int = 7000) -> str | None:
    """题目的隐藏测试（test_outputs.py / test.sh / verify.sh 等），拼成一段文本给判官做事后归因用。不盲评时才用。"""
    d = task_index(root).get(task_name)
    if not d or not (d / "tests").exists():
        return None
    parts = []
    for f in sorted((d / "tests").iterdir()):
        if f.suffix in (".py", ".sh") and f.is_file():
            txt = f.read_text(errors="replace")
            parts.append(f"### {f.name}\n{txt}")
    blob = "\n\n".join(parts)
    if len(blob) > max_chars:
        blob = blob[: max_chars // 2] + "\n[... omitted ...]\n" + blob[-max_chars // 2:]
    return blob or None


def _blob(files, max_chars):
    parts = []
    for f in files:
        try: txt = f.read_text(errors="replace")
        except Exception: continue
        if len(txt) > 20000: txt = txt[:20000] + "\n[... file truncated ...]"
        parts.append(f"### {f.name}\n{txt}")
    blob = "\n\n".join(parts)
    if len(blob) > max_chars: blob = blob[: max_chars // 2] + "\n[... omitted ...]\n" + blob[-max_chars // 2:]
    return blob or None


def full_context_for(task_name: str, root: str = "/root/.cache/harbor") -> dict:
    """事后归因判官的全 context：隐藏测试、环境定义（Dockerfile 与小文本文件）、参考解（solution/）。"""
    d = task_index(root).get(task_name)
    if not d: return {}
    out = {}
    tests = d / "tests"
    if tests.exists(): out["tests"] = _blob([f for f in sorted(tests.iterdir()) if f.is_file() and f.suffix in (".py", ".sh", ".txt", ".yaml", ".json")], 20000)
    env = d / "environment"
    if env.exists():
        files = [f for f in sorted(env.rglob("*")) if f.is_file() and f.stat().st_size < 6000 and f.suffix in ("", ".txt", ".md", ".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".c", ".cfg")]
        out["environment"] = _blob(files[:12], 12000)
    sol = d / "solution"
    if sol.exists(): out["solution"] = _blob([f for f in sorted(sol.iterdir()) if f.is_file()], 10000)
    return out
