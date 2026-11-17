"""One chat interface for every agent: chat(messages, tools) -> (message, usage).

`message` is normalised to {"content": str, "tool_calls": [{"name", "arguments"}]} and
`usage` to {"prompt_tokens", "completion_tokens", "seconds"}.
"""
from __future__ import annotations

import json
import time

import requests


class LLM:
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             json_only: bool = False) -> tuple[dict, dict]:
        raise NotImplementedError


class OllamaLLM(LLM):
    def __init__(self, model: str, host: str, seed: int = 0, temperature: float = 0.7,
                 num_ctx: int = 8192, think: bool = False, timeout_s: float = 600):
        self.model, self.host = model, host.rstrip("/")
        self.options = {"temperature": temperature, "seed": seed, "num_ctx": num_ctx}
        self.think, self.timeout_s = think, timeout_s

    def chat(self, messages, tools=None, json_only: bool = False):
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": self.options, "think": self.think}
        if tools:
            body["tools"] = tools
        if json_only:
            body["format"] = "json"
        t0 = time.time()
        resp = requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout_s)
        resp.raise_for_status()
        return parse_ollama_response(resp.json(), time.time() - t0)


def parse_ollama_response(data: dict, elapsed_s: float) -> tuple[dict, dict]:
    msg = data.get("message", {})
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_unparsed": args}
        calls.append({"name": fn.get("name", ""), "arguments": args})
    usage = {
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "completion_tokens": data.get("eval_count", 0),
        # Model time as reported by Ollama (load + prompt + generation), else wall time.
        "seconds": data["total_duration"] / 1e9 if data.get("total_duration") else elapsed_s,
    }
    return {"content": msg.get("content", ""), "tool_calls": calls}, usage


class AnthropicLLM(LLM):
    """Stub for a paid backend. Not implemented: the experiment runs on a local model.

    If added, read ANTHROPIC_API_KEY from .env (gitignored) and map Claude's tool_use
    blocks to the normalised message format above.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Anthropic backend is a stub; use backend: ollama")


def make_llm(llm_cfg: dict, seed: int) -> LLM:
    if llm_cfg["backend"] == "ollama":
        return OllamaLLM(llm_cfg["model"], llm_cfg["host"], seed=seed,
                         temperature=llm_cfg["temperature"],
                         think=llm_cfg.get("think", False))
    if llm_cfg["backend"] == "anthropic":
        return AnthropicLLM()
    raise ValueError(f"unknown backend {llm_cfg['backend']!r}")
