"""
call_summary.py
Generates a structured post-call summary + insights using OpenRouter.

Now briefing-aware: the agent is scored against their actual stated goal,
tone, and discount authority rather than generic debt-collection benchmarks.
Returns a dict the UI renders as cards.
"""

import json
from openai import OpenAI
from prompts import build_summary_system
import logger

log = logger.get("call_summary")
MODEL = "anthropic/claude-sonnet-4-5"

FALLBACK_SUMMARY: dict = {
    "outcome": "Call completed — summary unavailable.",
    "agent_score": 0,
    "sentiment_journey": "Unable to analyse.",
    "what_went_well": [],
    "what_to_improve": [],
    "key_facts_extracted": [],
    "suggested_next_action": "Review call recording manually.",
    "compliance_summary": "UNKNOWN — summary generation failed.",
}


def generate(transcript: list[dict], briefing: dict, persona: dict, client: OpenAI) -> dict:
    """
    Generate a post-call summary scored against the agent's briefing.

    Args:
        transcript: Full call transcript (list of {role, text, ts} dicts).
        briefing:   Pre-call briefing (agent name, goal, tone, discount, notes).
        persona:    Customer persona dict.
        client:     OpenAI-compatible LLM client.

    Returns:
        Structured summary dict ready for UI rendering.
    """
    log.info(
        f"Generating call summary — {len(transcript)} turns, "
        f"agent: {briefing.get('agent_name','?')}, goal: {briefing.get('goal','?')}"
    )

    system = build_summary_system(briefing=briefing, persona=persona)

    transcript_str = "\n".join(
        f"{'AGENT' if m['role'] == 'agent' else 'CUSTOMER'}: {m['text']}"
        for m in transcript
    )

    if not transcript_str.strip():
        log.warning("Empty transcript — returning fallback summary")
        return FALLBACK_SUMMARY

    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=800,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Here is the complete call transcript. Analyse it and return the JSON summary.\n\n"
                        f"{transcript_str}"
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        log.info(
            f"Summary generated — score: {result.get('agent_score')}, "
            f"outcome: {result.get('outcome','')[:60]}"
        )
        return result
    except Exception as e:
        log.error(f"Summary generation failed: {e}")
        return FALLBACK_SUMMARY