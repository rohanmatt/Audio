"""
call_logger.py
Appends a complete call record to calls_log.csv in the project root.

Each row gets a unique call_id (UUID4) and captures every piece of information
shown on the post-call screen: briefing, persona, summary, compliance, transcript,
and the agent's manually selected outcome + notes.

CSV is append-only — existing rows are never modified.
"""

import csv
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import logger

log = logger.get("call_logger")

CSV_PATH = Path("calls_log.csv")

# ── Column definitions — ORDER matters for CSV header ─────────────────────────
COLUMNS = [
    # Identity
    "call_id",
    "logged_at",
    "call_date",
    "call_start_time",
    "call_duration_secs",
    "turn_count",

    # Agent briefing
    "agent_name",
    "agent_goal",
    "agent_tone",
    "agent_max_discount_pct",
    "agent_notes",

    # Debtor / persona
    "debtor_name",
    "debtor_account_ref",
    "debtor_creditor",
    "debtor_debt_amount",
    "debtor_days_overdue",
    "debtor_situation",

    # Compliance
    "miranda_delivered",

    # AI summary fields
    "ai_outcome",
    "ai_agent_score",
    "ai_sentiment_journey",
    "ai_what_went_well",        # JSON list → pipe-separated string
    "ai_what_to_improve",       # JSON list → pipe-separated string
    "ai_key_facts_extracted",   # JSON list → pipe-separated string
    "ai_suggested_next_action",
    "ai_compliance_summary",

    # Manual log (agent-entered post-call)
    "logged_outcome",
    "logged_notes",

    # Full transcript (JSON string)
    "transcript_json",
]


def _list_to_str(val) -> str:
    """Convert a list to a pipe-separated string for readable CSV cells."""
    if isinstance(val, list):
        return " | ".join(str(v) for v in val)
    return str(val) if val else ""


def save(
    briefing: dict,
    persona: dict,
    summary: dict | None,
    transcript: list[dict],
    call_start: float,
    turn_count: int,
    miranda_done: bool,
    logged_outcome: str,
    logged_notes: str,
) -> str:
    """
    Append one call record to calls_log.csv.

    Returns the unique call_id assigned to this record.
    """
    call_id    = str(uuid.uuid4())
    now        = datetime.now()
    call_start_dt = datetime.fromtimestamp(call_start) if call_start else now
    duration_secs = int(now.timestamp() - call_start) if call_start else 0

    summary = summary or {}

    row = {
        # Identity
        "call_id":              call_id,
        "logged_at":            now.strftime("%Y-%m-%d %H:%M:%S"),
        "call_date":            call_start_dt.strftime("%Y-%m-%d"),
        "call_start_time":      call_start_dt.strftime("%H:%M:%S"),
        "call_duration_secs":   duration_secs,
        "turn_count":           turn_count,

        # Agent briefing
        "agent_name":           briefing.get("agent_name", ""),
        "agent_goal":           briefing.get("goal", ""),
        "agent_tone":           briefing.get("tone", ""),
        "agent_max_discount_pct": briefing.get("max_discount", ""),
        "agent_notes":          briefing.get("notes", ""),

        # Debtor / persona
        "debtor_name":          persona.get("name", ""),
        "debtor_account_ref":   persona.get("account_ref", ""),
        "debtor_creditor":      persona.get("creditor", ""),
        "debtor_debt_amount":   persona.get("debt_amount", ""),
        "debtor_days_overdue":  persona.get("days_overdue", ""),
        "debtor_situation":     persona.get("situation", ""),

        # Compliance
        "miranda_delivered":    "YES" if miranda_done else "NO",

        # AI summary
        "ai_outcome":               summary.get("outcome", ""),
        "ai_agent_score":           summary.get("agent_score", ""),
        "ai_sentiment_journey":     summary.get("sentiment_journey", ""),
        "ai_what_went_well":        _list_to_str(summary.get("what_went_well", [])),
        "ai_what_to_improve":       _list_to_str(summary.get("what_to_improve", [])),
        "ai_key_facts_extracted":   _list_to_str(summary.get("key_facts_extracted", [])),
        "ai_suggested_next_action": summary.get("suggested_next_action", ""),
        "ai_compliance_summary":    summary.get("compliance_summary", ""),

        # Manual log
        "logged_outcome":   logged_outcome,
        "logged_notes":     logged_notes,

        # Full transcript as compact JSON
        "transcript_json":  json.dumps(
            [{"role": m["role"], "text": m["text"],
              "ts": datetime.fromtimestamp(m["ts"]).strftime("%H:%M:%S")}
             for m in transcript],
            ensure_ascii=False
        ),
    }

    file_exists = CSV_PATH.exists()

    try:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
                log.info(f"Created new call log: {CSV_PATH.resolve()}")
            writer.writerow(row)

        log.info(f"Call logged — id: {call_id}, outcome: {logged_outcome}, score: {summary.get('agent_score','?')}")
        return call_id

    except Exception as e:
        log.error(f"Failed to write call log: {e}")
        raise