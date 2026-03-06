"""
agent_assist.py
Real-time supervisor assist — analyses transcript after each exchange.

Now briefing-aware: the assist prompt knows the agent's goal, tone, discount
ceiling, and pre-call notes so coaching is specific rather than generic.
"""

import json
from openai import OpenAI
from prompts import build_assist_system
import logger

log = logger.get("agent_assist")
MODEL = "anthropic/claude-sonnet-4-5"

FALLBACK_ASSIST: dict = {
    "suggestion": "Acknowledge the customer and keep the tone calm.",
    "script_line": "I understand — let me see what I can do to help you.",
    "sentiment": "neutral", "sentiment_score": 50, "call_stage": "opening",
    "compliance_alerts": [], "key_signals": [],
    "payment_plan": {"show": False, "balance": "", "options": []},
    "escalation_signals": [],
}


def analyse(transcript: list[dict], client: OpenAI,
            briefing: dict | None = None, persona: dict | None = None) -> dict:
    """
    Analyse the transcript and return a structured assist dict.

    Args:
        transcript: Full call transcript so far.
        client:     OpenAI-compatible LLM client.
        briefing:   Pre-call briefing dict (agent name, goal, tone, discount, notes).
                    If provided, coaching will be specific to the agent's stated objectives.
        persona:    Customer persona dict. Used alongside briefing for context.
    """
    log.info(f"Running agent assist analysis — {len(transcript)} messages in transcript")

    # Use briefing-aware prompt if briefing is supplied, else fall back to generic
    if briefing and persona:
        system = build_assist_system(briefing=briefing, persona=persona)
        log.info(f"Using briefing-aware assist — goal: '{briefing.get('goal','?')}', tone: '{briefing.get('tone','?')}'")
    else:
        from prompts import AGENT_ASSIST_SYSTEM
        system = AGENT_ASSIST_SYSTEM
        log.info("Using generic assist (no briefing supplied)")

    transcript_str = "\n".join(
        f"{'AGENT' if m['role'] == 'agent' else 'CUSTOMER'}: {m['text']}"
        for m in transcript
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=500,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Transcript so far:\n{transcript_str}"},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        log.info(
            f"Assist result — sentiment: {result.get('sentiment')} "
            f"({result.get('sentiment_score')}), stage: {result.get('call_stage')}"
        )
        return result
    except Exception as e:
        log.warning(f"Assist analysis failed, using fallback: {e}")
        return FALLBACK_ASSIST