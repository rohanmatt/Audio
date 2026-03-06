"""
logger.py
Structured terminal logging for Whispa.
All modules import `log` from here — output goes to stdout (visible in terminal).
"""

import logging
import sys
from datetime import datetime

# ── Setup ─────────────────────────────────────────────────────────────────────
_FMT = "%(asctime)s  %(levelname)-7s  %(name)-18s  %(message)s"
_DATE = "%H:%M:%S"

logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format=_FMT,
    datefmt=_DATE,
)

# One named logger per module — pass __name__ when importing
def get(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── Pretty dividers ───────────────────────────────────────────────────────────
def divider(label: str = "") -> None:
    bar = "─" * 60
    if label:
        print(f"\n{bar}\n  {label}\n{bar}")
    else:
        print(f"\n{bar}")


def transcript_line(role: str, text: str) -> None:
    """Print a single transcript turn in a readable format."""
    icon  = "🤖 AGENT   " if role == "agent" else "👤 CUSTOMER"
    ts    = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {icon} › {text}")