"""
ai_customer.py
AI customer persona — responds in character to agent lines.

If the customer ends the call, their reply will start with [CALL_ENDED]:
    [CALL_ENDED] Look, I've got nothing more to say. Goodbye.

Call customer_ended_call(reply) to check, strip_sentinel(reply) to get clean text.
"""

import re
from openai import OpenAI
from prompts import build_customer_system
import logger

log = logger.get("ai_customer")
MODEL = "anthropic/claude-sonnet-4-5"

CALL_END_SENTINEL = "[CALL_ENDED]"


def get_reply(persona: dict, transcript: list[dict], agent_text: str, client: OpenAI) -> str:
    """
    Returns the customer's reply as a plain string.
    If the string starts with CALL_END_SENTINEL the customer is hanging up.
    The sentinel prefix is preserved so the caller can detect and strip it.
    """
    log.info(f"Generating customer reply for persona: {persona['name']}")

    # Hang-up instructions are now baked into build_customer_system via prompts.py
    system = build_customer_system(persona)
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in transcript[-10:]:
        role = "user" if m["role"] == "agent" else "assistant"
        messages.append({"role": role, "content": m["text"]})
    if not messages or messages[-1].get("content") != agent_text:
        messages.append({"role": "user", "content": agent_text})

    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=200, messages=messages,
        )
        reply = resp.choices[0].message.content.strip()

        # ── Sentinel hardening ────────────────────────────────────────────────
        # Sometimes the model writes a stage direction before the sentinel,
        # e.g. "brief pause\n[CALL_ENDED] Goodbye."
        # Scan all lines for the sentinel and reformat cleanly.
        if CALL_END_SENTINEL in reply and not reply.startswith(CALL_END_SENTINEL):
            lines = reply.splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith(CALL_END_SENTINEL):
                    reply = "\n".join(lines[i:]).strip()
                    log.info("Sentinel found mid-reply — trimmed preceding stage directions")
                    break
            else:
                # Sentinel buried mid-sentence — extract the spoken part after it
                idx = reply.index(CALL_END_SENTINEL)
                reply = CALL_END_SENTINEL + " " + reply[idx + len(CALL_END_SENTINEL):].strip()

        # Strip residual stage directions after the spoken words.
        # e.g. "[CALL_ENDED] Goodbye. *hangs up*" → "[CALL_ENDED] Goodbye."
        if reply.startswith(CALL_END_SENTINEL):
            spoken = reply[len(CALL_END_SENTINEL):].strip()
            spoken = re.sub(r'[\*\(][^\*\)]*[\*\)]\.?$', '', spoken).strip()
            reply = f"{CALL_END_SENTINEL} {spoken}"
            log.info(f"Customer signalled hang-up. Final spoken: '{spoken}'")

        logger.transcript_line("customer", reply)
        return reply

    except Exception as e:
        log.error(f"Customer LLM error: {e}")
        return f"[Customer AI error: {e}]"


def customer_ended_call(reply: str) -> bool:
    """Returns True if the customer's reply signals a hang-up."""
    return CALL_END_SENTINEL in reply


def strip_sentinel(reply: str) -> str:
    """Strips the [CALL_ENDED] prefix, returning only the spoken text."""
    if reply.startswith(CALL_END_SENTINEL):
        return reply[len(CALL_END_SENTINEL):].strip()
    return reply