"""
ai_agent.py
AI debt collection agent — drives the conversation automatically.
"""

from openai import OpenAI
from prompts import build_agent_system
import logger

log = logger.get("ai_agent")
MODEL = "anthropic/claude-sonnet-4-5"


def get_next_line(persona: dict, briefing: dict, transcript: list[dict], client: OpenAI) -> str:
    log.info(f"Generating agent line — turn {len([m for m in transcript if m['role']=='agent']) + 1}")

    system = build_agent_system(persona, briefing)
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in transcript[-12:]:
        role = "assistant" if m["role"] == "agent" else "user"
        messages.append({"role": role, "content": m["text"]})
    if messages[-1]["role"] == "assistant":
        messages.append({"role": "user", "content": "[continue the call]"})

    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=150, messages=messages, temperature=0.7,
        )
        line = resp.choices[0].message.content.strip()
        logger.transcript_line("agent", line)
        return line
    except Exception as e:
        log.error(f"Agent LLM error: {e}")
        return f"[Agent AI error: {e}]"