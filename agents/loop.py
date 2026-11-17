"""A minimal tool-calling loop shared by every agent role."""
from __future__ import annotations

import json
import time
from pathlib import Path

from swarm.llm import LLM
from swarm.tools import ToolBox

PROMPT_TOKEN_LIMIT = 6000   # trim old exchanges before the 8k context window overflows
KEEP_LAST = 10


def _trim(messages: list[dict]) -> list[dict]:
    """Drop the oldest assistant/tool exchanges, keeping system + task + the last few."""
    head, body = messages[:2], messages[2:]
    while len(body) > KEEP_LAST:
        body = body[1:]
        while body and body[0]["role"] == "tool":   # never start with orphaned tool results
            body = body[1:]
    note = {"role": "user", "content": "(Older messages were removed to save space. "
                                       "Use read_log to see all results so far.)"}
    return head + [note] + body


def nudge_text(box: ToolBox) -> str:
    """Reminder sent when the model answers without a tool call. It must name a tool this
    role has: the critic was once told to call submit_claim, which it does not have."""
    if box.role == "critic":
        return "Reply with a tool call, not text. Call decide for every claim you have not decided."
    return (f"Reply with a tool call, not text. Runs left: {box.budget.left}. "
            "When you have no runs left, call submit_claim.")


def _chat_with_retry(llm, messages, tools, tries: int = 3):
    for i in range(tries):
        try:
            return llm.chat(messages, tools)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def run_agent(llm: LLM, system: str, task: str, box: ToolBox, *, store, condition: str,
              repeat: int, max_turns: int, transcript: Path, done) -> list[dict]:
    """Run until done(box) is true or max_turns is reached. Returns the transcript."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    log = []
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("")   # written one line per turn, so an interrupted run keeps a record
    nudges = 0
    for turn in range(max_turns):
        try:
            msg, usage = _chat_with_retry(llm, messages, box.schemas())
        except Exception as e:  # still failing after retries: record and stop this agent
            log.append({"turn": turn, "error": repr(e)})
            with open(transcript, "a") as f:
                f.write(json.dumps(log[-1]) + "\n")
            break
        store.add_llm_call(condition, repeat, box.agent, usage["prompt_tokens"],
                           usage["completion_tokens"], usage["seconds"])
        entry = {"turn": turn, "t": time.time(), "content": msg["content"],
                 "tool_calls": msg["tool_calls"], "usage": usage, "results": []}
        messages.append({"role": "assistant", "content": msg["content"],
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in msg["tool_calls"]]})
        if msg["tool_calls"]:
            for c in msg["tool_calls"]:
                result = box.call(c["name"], c["arguments"])
                entry["results"].append(result)
                messages.append({"role": "tool", "content": result, "tool_name": c["name"]})
        else:
            nudges += 1
            messages.append({"role": "user", "content": nudge_text(box)})
        log.append(entry)
        with open(transcript, "a") as f:
            f.write(json.dumps(entry) + "\n")
        if done(box):
            break
        if usage["prompt_tokens"] > PROMPT_TOKEN_LIMIT:
            messages = _trim(messages)
    return log
