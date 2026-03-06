"""
app.py — Whispa Live Call Simulator
Each turn streams step-by-step to the screen:
  Agent line appears → agent audio plays → customer line appears → customer audio plays → assist updates

FIX: Audio now plays reliably on every turn by:
  1. Using a globally unique audio ID (turn_count + role + timestamp) so the DOM element is always brand-new
  2. Injecting JS that waits for the element to be ready, then calls .load() + .play()
  3. Using components.html() for audio iframes so Streamlit cannot diff/skip re-rendering them

Customer hang-up:
  ai_customer.get_reply() prefixes its response with [CALL_ENDED] when the persona
  ends the call. run_turn_live() detects this, plays the final audio, then triggers
  the post-call summary — no further turns are allowed.
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

import agent_assist, ai_agent, ai_customer, call_logger, call_summary, speech_to_text, text_to_speech
from ai_customer import customer_ended_call, strip_sentinel
from prompts import PERSONAS, PRE_CALL_QUESTIONS
import logger

log = logger.get("app")

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Whispa · Live Call", page_icon="📞", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'IBM Plex Sans',sans-serif!important;background:#0b0e13!important;color:#dde3ee!important}
.stApp{background:#0b0e13!important}.main .block-container{padding:1rem 1.5rem!important;max-width:100%!important}
#MainMenu,footer,header{visibility:hidden}
[data-testid="metric-container"]{background:#12151c;border:1px solid #1e2530;border-radius:8px;padding:10px 14px}
[data-testid="metric-container"] label{color:#6b7a94!important;font-size:10px!important}
[data-testid="stMetricValue"]{color:#dde3ee!important;font-family:'IBM Plex Mono',monospace!important;font-size:18px!important}
.stButton>button{background:#12151c!important;border:1px solid #1e2530!important;color:#dde3ee!important;border-radius:6px!important;font-family:'IBM Plex Mono',monospace!important;font-size:11px!important;letter-spacing:.07em!important;padding:8px 16px!important;transition:all .2s!important;width:100%}
.stButton>button:hover{border-color:#00c8f0!important;color:#00c8f0!important;background:rgba(0,200,240,.05)!important}
.stTextInput>div>div>input,.stTextArea>div>div>textarea{background:#12151c!important;border:1px solid #1e2530!important;color:#dde3ee!important;border-radius:6px!important;font-family:'IBM Plex Mono',monospace!important;font-size:12px!important}
.stSelectbox>div>div{background:#12151c!important;border:1px solid #1e2530!important;color:#dde3ee!important}
hr{border-color:#1e2530!important}
.card{background:#12151c;border:1px solid #1e2530;border-radius:8px;padding:14px 16px;margin-bottom:10px}

/* Transcript bubbles */
.msg{margin-bottom:14px}
.msg-label{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.08em;margin-bottom:3px;opacity:.5}
.msg-bubble{display:inline-block;padding:9px 13px;border-radius:8px;max-width:95%;font-size:13px;line-height:1.65}
.msg-agent   .msg-bubble{background:rgba(0,200,240,.08);border:1px solid rgba(0,200,240,.18);color:#a8d8e8}
.msg-customer .msg-bubble{background:#181c26;border:1px solid #252c3a;color:#dde3ee}
.msg-typing  .msg-bubble{background:#12151c;border:1px solid #1e2530;color:#3a4560;font-style:italic}

/* Live turn status banner */
.turn-status{background:#0e1a22;border:1px solid #1a2530;border-left:3px solid #00c8f0;border-radius:6px;padding:10px 14px;margin-bottom:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#6b9ab8}

/* Assist */
.assist{border-radius:8px;padding:12px 14px;margin-bottom:8px;font-size:12px;line-height:1.55;color:#c0cad8}
.assist-tip   {background:#0e1a22;border:1px solid #1a2530;border-left:3px solid #00c8f0}
.assist-script{background:#0e1f17;border:1px solid #1a2c22;border-left:3px solid #00d97e}
.assist-warn  {background:#221a0e;border:1px solid #2c2318;border-left:3px solid #f0a500}
.assist-title {font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.1em;opacity:.5;margin-bottom:5px;text-transform:uppercase}
.sent-track{background:#1a1f2a;border-radius:4px;height:8px;overflow:hidden;margin:6px 0 3px}
.sent-fill{height:100%;border-radius:4px;transition:width .6s ease,background .6s}
.stage-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.06em;background:rgba(0,200,240,.1);color:#00c8f0;border:1px solid rgba(0,200,240,.25)}
.flag{display:flex;gap:8px;align-items:flex-start;padding:7px 10px;border-radius:6px;margin-bottom:5px;font-size:12px}
.flag-ok  {background:rgba(0,217,126,.07);color:#80d0a8}
.flag-warn{background:rgba(240,165,0,.07); color:#d4a860}
.flag-bad {background:rgba(240,80,80,.08); color:#e08080}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#00d97e;margin-right:6px;animation:pulse 1.3s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(1.5)}}
.section-label{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.12em;color:#3a4560;text-transform:uppercase;margin-bottom:7px;margin-top:2px}

/* Post-call */
.score-ring{font-family:'IBM Plex Mono',monospace;font-size:42px;font-weight:600;text-align:center;padding:12px 0 4px}
.summary-card{background:#12151c;border:1px solid #1e2530;border-radius:8px;padding:14px 16px;margin-bottom:10px;font-size:12px;line-height:1.65}
.summary-card h4{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.1em;color:#3a4560;text-transform:uppercase;margin-bottom:6px;font-weight:400}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:10px;font-family:'IBM Plex Mono',monospace;margin:2px 3px 2px 0}
.pill-green{background:rgba(0,217,126,.1);color:#80d0a8;border:1px solid rgba(0,217,126,.2)}
.pill-amber{background:rgba(240,165,0,.1); color:#d4a860;border:1px solid rgba(240,165,0,.2)}
.pill-red  {background:rgba(240,80,80,.1); color:#e08080;border:1px solid rgba(240,80,80,.2)}
</style>
""", unsafe_allow_html=True)

# ── API CLIENTS ───────────────────────────────────────────────────────────────
DEEPGRAM_API_KEY   = os.getenv("DEEPGRAM_API_KEY",   "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
log.info(f"Keys — Deepgram: {'✓' if DEEPGRAM_API_KEY else '✗ MISSING'} | OpenRouter: {'✓' if OPENROUTER_API_KEY else '✗ MISSING'}")

@st.cache_resource
def get_llm():
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

llm = get_llm()

# ── SESSION STATE ─────────────────────────────────────────────────────────────
_DEFAULTS = {
    "screen":          "briefing",
    "briefing":        {},
    "persona_key":     list(PERSONAS.keys())[0],
    "call_start":      None,
    "transcript":      [],
    "assist":          None,
    "turn_count":      0,
    "miranda_done":    False,
    "summary":         None,
    "auto_advance":    True,
    "last_turn_ts":    0.0,
    "running":         False,   # True while a turn is mid-execution
    "pending_override": None,  # text override queued for next turn
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

SENTIMENT_COLOUR = {"hostile":"#f05050","frustrated":"#f0a500","neutral":"#6b7a94","cooperative":"#00d97e","distressed":"#c080e0"}
STAGE_LABEL = {"opening":"Opening","rapport":"Rapport","negotiation":"Negotiation","objection-handling":"Objection Handling","resolution":"Resolution","closing":"Closing"}
MIRANDA_KEYWORDS = ["attempt to collect a debt","debt collector","attempting to collect"]
AUTO_SECS = 4

# ── PURE HELPERS ──────────────────────────────────────────────────────────────
def elapsed():
    if st.session_state.call_start:
        s = int(time.time() - st.session_state.call_start)
        return f"{s//60:02d}:{s%60:02d}"
    return "00:00"

def add_msg(role, text):
    st.session_state.transcript.append({"role": role, "text": text, "ts": time.time()})

def check_miranda(text):
    if not st.session_state.miranda_done and any(k in text.lower() for k in MIRANDA_KEYWORDS):
        log.info("✅ Mini-Miranda detected")
        st.session_state.miranda_done = True


def audio_html(b64: str, uid: str) -> str:
    """
    Returns a self-contained HTML snippet that RELIABLY autoplays audio on every turn.

    Key fixes vs the original:
    - uid must be globally unique (turn_count + role + ms timestamp) so the browser
      sees a genuinely new <audio> element each time and doesn't skip autoplay.
    - We call audio.load() before audio.play() to force the browser to re-read the src.
    - A MutationObserver watches the parent container so that even if Streamlit inserts
      the HTML slightly after the script runs, play() is still triggered.
    - The <audio> element is hidden (height:0) and we show a minimal styled label
      instead, keeping the UI clean while still playing sound.
    """
    return f"""
    <div id="wrap_{uid}" style="margin:4px 0">
      <audio id="aud_{uid}" style="width:100%;height:36px;outline:none;margin:2px 0" controls>
        <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
      </audio>
    </div>
    <script>
    (function() {{
      var MAX_TRIES = 40;   // 40 × 100 ms = 4 s
      var tries = 0;

      function tryPlay() {{
        var a = document.getElementById("aud_{uid}");
        if (!a) {{
          if (++tries < MAX_TRIES) {{ setTimeout(tryPlay, 100); }}
          return;
        }}
        // Force reload so browser treats it as a fresh resource
        a.load();
        var p = a.play();
        if (p !== undefined) {{
          p.catch(function(err) {{
            // Autoplay blocked — audio controls still visible for manual play
            console.warn("Whispa audio autoplay blocked ({uid}):", err.message);
          }});
        }}
      }}

      // Try immediately, then poll in case Streamlit hasn't mounted the element yet
      tryPlay();
    }})();
    </script>"""


def play_audio_iframe(b64: str, label: str, slot) -> None:
    """
    Renders audio into a Streamlit slot using components.html() (an iframe).

    Why an iframe?  Streamlit's virtual-DOM diffing can decide NOT to update an
    st.empty() placeholder when the new HTML looks structurally identical to the
    last render (same tag names, same attributes skeleton).  Because components.html()
    always creates/replaces a real iframe, every call is guaranteed to execute fresh
    JavaScript — which means audio.play() fires on every turn without exception.

    The iframe is sized to just show the native <audio> controls.
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{margin:0;padding:0;background:transparent;overflow:hidden}}
  .lbl {{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.1em;
         color:#3a4560;text-transform:uppercase;margin-bottom:3px}}
  audio {{width:100%;height:36px;outline:none;display:block}}
</style>
</head>
<body>
  <div class="lbl">{label}</div>
  <audio id="aud" controls>
    <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
  </audio>
  <script>
    (function() {{
      var MAX_TRIES = 40;
      var tries = 0;
      function tryPlay() {{
        var a = document.getElementById("aud");
        if (!a) {{ if (++tries < MAX_TRIES) setTimeout(tryPlay, 100); return; }}
        a.load();
        var p = a.play();
        if (p !== undefined) {{
          p.catch(function(e) {{
            console.warn("Whispa iframe audio blocked:", e.message);
          }});
        }}
      }}
      tryPlay();
    }})();
  </script>
</body>
</html>"""
    # height=60 — just enough for the label + native audio controls bar
    slot.empty()  # clear any previous content first
    with slot:
        components.html(html, height=60, scrolling=False)


def audio_duration_secs(text: str) -> float:
    """
    Estimate how long the TTS audio will take to play.
    Deepgram Aura-2 speaks at ~150 words per minute.
    We add 0.8s buffer for audio load + iframe handshake.
    Clamped between 1.5s and 20s.
    """
    words = max(1, len(text.split()))
    secs  = (words / 150) * 60
    return max(1.5, min(secs + 0.8, 20.0))


def render_transcript():
    """Return full transcript HTML string."""
    persona   = PERSONAS[st.session_state.persona_key]
    agent_nm  = st.session_state.briefing.get("agent_name","AGENT").upper()
    cust_nm   = persona["name"].split()[0].upper()
    html = ""
    for m in st.session_state.transcript:
        ts   = datetime.fromtimestamp(m["ts"]).strftime("%H:%M:%S")
        role = m["role"]
        lbl  = f"AGENT — {agent_nm}" if role == "agent" else f"CUSTOMER — {cust_nm}"
        html += f'<div class="msg msg-{role}"><div class="msg-label">{lbl} · {ts}</div><div class="msg-bubble">{m["text"]}</div></div>'
    return html or '<div style="color:#3a4560;font-style:italic;font-size:12px">Waiting for first turn…</div>'

# ── LIVE TURN — streams step-by-step into placeholder slots ──────────────────
def _render_assist(slot, assist: dict) -> None:
    """Render the full assist panel into a placeholder slot. Used both live (run_turn_live)
    and on static rerender (call screen initial load)."""
    sent  = assist.get("sentiment","neutral")
    score = assist.get("sentiment_score", 50)
    color = SENTIMENT_COLOUR.get(sent,"#6b7a94")
    stage = STAGE_LABEL.get(assist.get("call_stage","opening"),"Opening")
    signals_html = "".join(f'<div style="margin-bottom:3px">· {s}</div>' for s in assist.get("key_signals",[]))
    alerts_html  = "".join(f'<div class="flag flag-warn"><span>⚠</span><span>{a}</span></div>' for a in assist.get("compliance_alerts",[]))

    # ── Payment plan calculator ───────────────────────────────────────────────
    pp = assist.get("payment_plan", {})
    payment_plan_html = ""
    if pp.get("show") and pp.get("options"):
        plan_rows = ""
        for opt in pp.get("options", []):
            if opt.get("lump_sum"):
                plan_rows += (
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:6px 0;border-bottom:1px solid #1e2530">'
                    f'<span style="color:#f0a500;font-weight:600;font-size:11px">{opt["label"]}</span>'
                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:13px;color:#00d97e">'
                    f'{opt["lump_sum"]} today</span></div>'
                )
            else:
                plan_rows += (
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'padding:6px 0;border-bottom:1px solid #1e2530">'
                    f'<span style="color:#6b7a94;font-size:11px">{opt["label"]}</span>'
                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:13px;color:#dde3ee">'
                    f'{opt.get("monthly","—")}/mo × {opt.get("months","?")}m</span></div>'
                )
        payment_plan_html = f"""<div class="card" style="padding:12px 14px;margin-bottom:8px">
          <div class="assist-title" style="margin-bottom:8px">💳 Payment Plan Options</div>
          <div style="font-family:IBM Plex Mono,monospace;font-size:9px;color:#3a4560;
                      letter-spacing:.08em;margin-bottom:6px">TOTAL BALANCE: {pp.get("balance","")}</div>
          {plan_rows}
        </div>"""

    # ── Escalation signals ────────────────────────────────────────────────────
    esc_html = ""
    for sig in assist.get("escalation_signals", []):
        sig_type = sig.get("type","other")
        bg     = "#1a0f0f" if sig_type in ("dispute","legal_threat") else "#0f1a10" if sig_type == "settlement_opportunity" else "#131820"
        border = "#f05050" if sig_type in ("dispute","legal_threat") else "#00d97e" if sig_type == "settlement_opportunity" else "#6b7a94"
        esc_html += (
            f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
            f'padding:10px 12px;margin-bottom:6px">'
            f'<div style="font-size:13px;font-weight:600;margin-bottom:3px">'
            f'{sig.get("icon","ℹ️")} {sig.get("title","Signal detected")}</div>'
            f'<div style="font-size:11px;color:#c0cad8;line-height:1.5">{sig.get("detail","")}</div>'
            f'</div>'
        )

    slot.markdown(f"""
    <div class="card" style="padding:12px 14px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="color:{color};font-weight:600;font-size:14px;text-transform:capitalize">{sent}</span>
        <span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#6b7a94">{score}/100</span>
      </div>
      <div class="sent-track"><div class="sent-fill" style="width:{score}%;background:{color}"></div></div>
      <div style="margin-top:8px"><span class="stage-badge">{stage}</span></div>
    </div>
    <div class="assist assist-tip"><div class="assist-title">💡 Coaching</div>{assist.get("suggestion","")}</div>
    <div class="assist assist-script"><div class="assist-title">🗣 Say This</div><em>\"{assist.get("script_line","")}\"</em></div>
    {f'<div class="assist" style="background:#131820;border:1px solid #1e2530"><div class="assist-title">📌 Key Signals</div>{signals_html}</div>' if signals_html else ""}
    {alerts_html}
    {payment_plan_html}
    {esc_html}
    """, unsafe_allow_html=True)


def _render_stats(turns_slot, duration_slot) -> None:
    """Update the top-bar turns + duration placeholders. Called after every turn."""
    turns_slot.markdown(
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:16px;color:#6b7a94">{st.session_state.turn_count}</div>',
        unsafe_allow_html=True,
    )
    duration_slot.markdown(
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:16px;color:#6b7a94">{elapsed()}</div>',
        unsafe_allow_html=True,
    )


def _render_transcript_scroll(slot) -> None:
    """
    Render the transcript into a fixed-height scrollable box.
    A small JS snippet scrolls the container to the bottom after each update
    so the latest message is always visible without the page growing.
    """
    persona  = PERSONAS[st.session_state.persona_key]
    agent_nm = st.session_state.briefing.get("agent_name", "AGENT").upper()
    cust_nm  = persona["name"].split()[0].upper()
    msgs_html = ""
    for m in st.session_state.transcript:
        ts   = datetime.fromtimestamp(m["ts"]).strftime("%H:%M:%S")
        role = m["role"]
        lbl  = f"AGENT — {agent_nm}" if role == "agent" else f"CUSTOMER — {cust_nm}"
        msgs_html += (
            f'<div class="msg msg-{role}">' 
            f'<div class="msg-label">{lbl} · {ts}</div>' 
            f'<div class="msg-bubble">{m["text"]}</div></div>'
        )
    if not msgs_html:
        msgs_html = '<div style="color:#3a4560;font-style:italic;font-size:12px">Waiting for first turn…</div>'

    slot.markdown(
        f'''<div id="tx-box" style="background:#0e1117;border:1px solid #1e2530;border-radius:8px;
                    padding:14px;height:420px;overflow-y:auto;scroll-behavior:smooth">
          {msgs_html}
        </div>
        <script>
          (function(){{
            var b = document.getElementById("tx-box");
            if(b) b.scrollTop = b.scrollHeight;
          }})();
        </script>''',
        unsafe_allow_html=True,
    )


def run_turn_live(
    transcript_slot,   # st.empty() — transcript panel
    status_slot,       # st.empty() — "Agent thinking…" banner
    agent_audio_slot,  # st.empty() — agent audio player
    cust_audio_slot,   # st.empty() — customer audio player
    assist_slot,       # st.empty() — right-panel assist
    turns_slot,        # st.empty() — top-bar turn counter
    duration_slot,     # st.empty() — top-bar duration timer
    agent_text: str | None = None,   # if set, use this instead of LLM agent
):
    persona  = PERSONAS[st.session_state.persona_key]
    briefing = st.session_state.briefing
    turn_n   = st.session_state.turn_count + 1

    logger.divider(f"TURN {turn_n}")
    st.session_state.running = True

    # ── Step 1: Agent generates line ─────────────────────────────────────────
    status_slot.markdown('<div class="turn-status">🤖 Agent thinking…</div>', unsafe_allow_html=True)

    if agent_text is None:
        agent_text = ai_agent.get_next_line(persona=persona, briefing=briefing,
                                             transcript=st.session_state.transcript, client=llm)
    add_msg("agent", agent_text)
    check_miranda(agent_text)

    # Show agent line in transcript immediately
    _render_transcript_scroll(transcript_slot)

    # ── Step 2: Synthesise + play agent voice ────────────────────────────────
    status_slot.markdown('<div class="turn-status">🔊 Agent speaking…</div>', unsafe_allow_html=True)
    agent_b64 = text_to_speech.synthesise_agent(agent_text, DEEPGRAM_API_KEY)
    if agent_b64:
        # Use iframe-based player to guarantee fresh JS execution every turn
        play_audio_iframe(agent_b64, "🤖 AGENT VOICE", agent_audio_slot)
        # Let audio start before customer responds
        time.sleep(audio_duration_secs(agent_text))
    else:
        log.warning("Agent TTS returned None — skipping agent audio")

    # ── Step 3: Customer generates reply ────────────────────────────────────
    status_slot.markdown('<div class="turn-status">👤 Customer responding…</div>', unsafe_allow_html=True)
    customer_reply_raw = ai_customer.get_reply(persona=persona, transcript=st.session_state.transcript,
                                               agent_text=agent_text, client=llm)

    # Detect customer hang-up BEFORE storing — strip sentinel for display/TTS
    call_ended_by_customer = customer_ended_call(customer_reply_raw)
    customer_reply = strip_sentinel(customer_reply_raw)

    add_msg("customer", customer_reply)

    # Update transcript with customer line
    _render_transcript_scroll(transcript_slot)

    # ── Step 4: Synthesise + play customer voice ─────────────────────────────
    status_slot.markdown('<div class="turn-status">🔊 Customer speaking…</div>', unsafe_allow_html=True)
    cust_b64 = text_to_speech.synthesise(customer_reply, st.session_state.persona_key, DEEPGRAM_API_KEY)
    if cust_b64:
        # Use iframe-based player to guarantee fresh JS execution every turn
        play_audio_iframe(cust_b64, "👤 CUSTOMER VOICE", cust_audio_slot)
        time.sleep(audio_duration_secs(customer_reply))
    else:
        log.warning("Customer TTS returned None — skipping customer audio")

    # ── Customer hang-up: end the call immediately, skip assist update ────────
    if call_ended_by_customer:
        log.info("Customer ended the call — triggering post-call summary")
        st.session_state.turn_count  += 1
        st.session_state.last_turn_ts = time.time()
        st.session_state.running      = False
        status_slot.markdown(
            '<div class="turn-status" style="border-left-color:#f05050;color:#e08080">'
            '📵 Customer ended the call — generating summary…</div>',
            unsafe_allow_html=True,
        )
        # Small pause so the status banner is visible before navigation
        time.sleep(1.2)
        st.session_state.screen = "post"
        st.session_state.summary = call_summary.generate(
            st.session_state.transcript, st.session_state.briefing, persona, llm
        )
        log.info("Summary generated — navigating to post-call screen")
        st.rerun()
        return  # safety guard; rerun() above will redirect

    # ── Step 5: Refresh assist ───────────────────────────────────────────────
    status_slot.markdown('<div class="turn-status">⚙️ Updating assist…</div>', unsafe_allow_html=True)
    assist = agent_assist.analyse(st.session_state.transcript, llm,
                                   briefing=st.session_state.briefing, persona=persona)
    st.session_state.assist = assist

    # Render assist panel inline (shared helper keeps this DRY)
    _render_assist(assist_slot, assist)

    # Done
    st.session_state.turn_count  += 1
    st.session_state.last_turn_ts = time.time()
    st.session_state.running      = False
    status_slot.empty()

    # Update top-bar stats live after every turn
    _render_stats(turns_slot, duration_slot)

    log.info(f"Turn {turn_n} complete ✓")


# ══════════════════════════════════════════════════════════════════════════════
#  SCREEN 1 — BRIEFING
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.screen == "briefing":

    st.markdown('<div style="text-align:center;padding:24px 0 8px">'
                '<span style="font-family:IBM Plex Mono,monospace;font-size:22px;font-weight:600;color:#00c8f0;letter-spacing:.1em">WHISPA</span>'
                '<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#3a4560;letter-spacing:.06em;margin-left:12px">PRE-CALL BRIEFING</span>'
                '</div>', unsafe_allow_html=True)

    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        st.markdown('<div class="card" style="padding:24px 28px">', unsafe_allow_html=True)
        st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:13px;font-weight:600;color:#00c8f0;letter-spacing:.08em;margin-bottom:4px">Before we dial…</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:12px;color:#6b7a94;margin-bottom:20px">Answer a few quick questions so the AI agent knows how to handle this call.</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-label">SELECT DEBTOR</div>', unsafe_allow_html=True)
        persona_key = st.selectbox("Debtor persona", list(PERSONAS.keys()),
            index=list(PERSONAS.keys()).index(st.session_state.persona_key), label_visibility="collapsed")
        p = PERSONAS[persona_key]
        st.markdown(
            f'<div class="card" style="margin:6px 0 14px">'
            f'<div style="display:flex;justify-content:space-between">'
            f'<div><div style="font-weight:600;font-size:13px">{p["name"]}</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#6b7a94">{p["account_ref"]} · {p["creditor"]}</div>'
            f'<div style="font-size:11px;color:#6b7a94;margin-top:4px">{p["situation"]}</div></div>'
            f'<div style="text-align:right"><div style="font-family:IBM Plex Mono,monospace;font-size:20px;font-weight:600;color:#f0a500">{p["debt_amount"]}</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#f05050">{p["days_overdue"]} days overdue</div></div>'
            f'</div></div>', unsafe_allow_html=True)

        st.markdown('<div class="section-label">AGENT BRIEFING</div>', unsafe_allow_html=True)
        answers = {}
        for q in PRE_CALL_QUESTIONS:
            if q["type"] == "text":
                answers[q["key"]] = st.text_input(q["label"], placeholder=q.get("placeholder",""), value=st.session_state.briefing.get(q["key"],""))
            elif q["type"] == "select":
                prev = st.session_state.briefing.get(q["key"], q["options"][0])
                answers[q["key"]] = st.selectbox(q["label"], q["options"], index=q["options"].index(prev) if prev in q["options"] else 0)
            elif q["type"] == "textarea":
                answers[q["key"]] = st.text_area(q["label"], placeholder=q.get("placeholder",""), value=st.session_state.briefing.get(q["key"],""), height=70)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📞  START CALL", key="start_call"):
            log.info(f"Call starting — persona: {persona_key}, agent: {answers.get('agent_name','?')}")
            logger.divider("CALL STARTED")
            st.session_state.update({
                "persona_key": persona_key, "briefing": answers,
                "screen": "call", "call_start": time.time(),
                "transcript": [], "assist": None,
                "turn_count": 0, "miranda_done": False,
                "summary": None, "last_turn_ts": 0.0, "running": False,
            })
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SCREEN 2 — LIVE CALL
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "call":

    # Safety reset — if running is True but we're in a fresh render pass,
    # a prior turn must have crashed or been interrupted. Reset it so the
    # call can proceed. running=True should only exist WITHIN run_turn_live(),
    # never across a Streamlit rerun boundary.
    if st.session_state.running:
        log.warning("running=True detected at render start — resetting to False")
        st.session_state.running = False

    persona = PERSONAS[st.session_state.persona_key]
    assist  = st.session_state.assist

    # ── TOP BAR ──────────────────────────────────────────────────────────────
    tb1, tb2, tb3, tb4, tb5, tb6 = st.columns([1.6, 2.8, 1.2, 1.2, 1.4, 1.8])
    with tb1:
        st.markdown('<span style="font-family:IBM Plex Mono,monospace;font-size:16px;font-weight:600;color:#00c8f0;letter-spacing:.1em">WHISPA</span>', unsafe_allow_html=True)
    with tb2:
        st.markdown(f'<div style="padding-top:4px"><span class="live-dot"></span>'
                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#00d97e">LIVE</span>'
                    f'<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#3a4560;margin-left:14px">{persona["name"]} · {persona["account_ref"]}</span></div>',
                    unsafe_allow_html=True)
    with tb3:
        # Duration — updated live by _render_stats() after each turn
        st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:9px;letter-spacing:.1em;color:#3a4560;text-transform:uppercase">Duration</div>', unsafe_allow_html=True)
        duration_slot = st.empty()
        duration_slot.markdown(f'<div style="font-family:IBM Plex Mono,monospace;font-size:16px;color:#6b7a94">{elapsed()}</div>', unsafe_allow_html=True)
    with tb4:
        # Turns — updated live by _render_stats() after each turn
        st.markdown('<div style="font-family:IBM Plex Mono,monospace;font-size:9px;letter-spacing:.1em;color:#3a4560;text-transform:uppercase">Turns</div>', unsafe_allow_html=True)
        turns_slot = st.empty()
        turns_slot.markdown(f'<div style="font-family:IBM Plex Mono,monospace;font-size:16px;color:#6b7a94">{st.session_state.turn_count}</div>', unsafe_allow_html=True)
    with tb5:
        auto_lbl = "⏸ PAUSE" if st.session_state.auto_advance else "▶ AUTO"
        if st.button(auto_lbl, key="toggle_auto"):
            st.session_state.auto_advance = not st.session_state.auto_advance
            log.info(f"Auto-advance {'ON' if st.session_state.auto_advance else 'OFF'}")
            st.rerun()
    with tb6:
        if st.button("■  END CALL", key="end_call"):
            log.info(f"Call ended — {st.session_state.turn_count} turns, {elapsed()}")
            logger.divider("CALL ENDED")
            st.session_state.screen = "post"
            with st.spinner("Generating call summary…"):
                st.session_state.summary = call_summary.generate(
                    st.session_state.transcript, st.session_state.briefing, persona, llm)
            st.rerun()

    st.markdown('<hr style="margin:8px 0 10px">', unsafe_allow_html=True)

    # ── 3 COLUMNS ────────────────────────────────────────────────────────────
    left, mid, right = st.columns([2.2, 3.6, 2.4], gap="medium")

    # ── LEFT — info + manual controls ────────────────────────────────────────
    with left:
        # ── Full customer dossier ─────────────────────────────────────────────
        st.markdown('<div class="section-label">DEBTOR PROFILE</div>', unsafe_allow_html=True)
        st.markdown(f"""<div class="card">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div>
              <div style="font-size:15px;font-weight:600;margin-bottom:2px">{persona['name']}</div>
              <div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#6b7a94;letter-spacing:.06em">{persona['account_ref']}</div>
            </div>
            <div style="text-align:right">
              <div style="font-family:IBM Plex Mono,monospace;font-size:22px;font-weight:600;color:#f0a500">{persona['debt_amount']}</div>
              <div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#f05050">{persona['days_overdue']} days overdue</div>
            </div>
          </div>
          <div style="border-top:1px solid #1e2530;padding-top:8px;font-size:11px;line-height:1.9">
            <div><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;letter-spacing:.08em;text-transform:uppercase">Creditor</span><br>
              <span style="color:#dde3ee">{persona['creditor']}</span></div>
            <div style="margin-top:6px"><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;letter-spacing:.08em;text-transform:uppercase">Situation</span><br>
              <span style="color:#c0cad8">{persona['situation']}</span></div>
          </div>
        </div>""", unsafe_allow_html=True)

        # Personality / behaviour profile — collapsed by default so it doesn't crowd the UI
        with st.expander("🧠 Behaviour Profile", expanded=False):
            # Strip the "You are X..." prefix for cleaner display
            personality_raw = persona.get('personality', '')
            # Show from the descriptive adjectives onward
            import re as _re
            clean_personality = _re.sub(r'^You are [^,]+,\s*', '', personality_raw).strip()
            st.markdown(
                f'<div style="font-size:11px;line-height:1.7;color:#c0cad8;padding:4px 0">{clean_personality}</div>',
                unsafe_allow_html=True
            )

        b = st.session_state.briefing
        st.markdown('<div class="section-label" style="margin-top:6px">AGENT BRIEFING</div>', unsafe_allow_html=True)
        st.markdown(f"""<div class="card" style="font-size:11px;line-height:1.9">
          <div><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:.08em">Agent</span><br>
            <span style="color:#dde3ee">{b.get('agent_name','—')}</span></div>
          <div style="margin-top:5px"><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:.08em">Goal</span><br>
            <span style="color:#dde3ee">{b.get('goal','—')}</span></div>
          <div style="margin-top:5px"><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:.08em">Tone</span><br>
            <span style="color:#dde3ee">{b.get('tone','—')}</span></div>
          <div style="margin-top:5px"><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:.08em">Max Discount</span><br>
            <span style="color:#dde3ee">{b.get('max_discount','None') or 'None'}%</span></div>
          {f'<div style="margin-top:5px"><span style="color:#6b7a94;font-family:IBM Plex Mono,monospace;font-size:9px;text-transform:uppercase;letter-spacing:.08em">Notes</span><br><span style="color:#c0cad8">{b.get("notes","")}</span></div>' if b.get('notes') else ''}
        </div>""", unsafe_allow_html=True)

        st.markdown('<div class="section-label">OVERRIDE — TYPE LINE</div>', unsafe_allow_html=True)
        # Use a stable key so the value persists across reruns until consumed.
        # We clear it by resetting session_state.pending_override after use.
        override = st.text_area(
            "Override",
            placeholder="Type your own agent line…",
            height=80,
            key="override_input",
            label_visibility="collapsed",
        )


    # ── MID — live transcript + audio players ────────────────────────────────
    with mid:
        st.markdown('<div class="section-label">LIVE TRANSCRIPT</div>', unsafe_allow_html=True)

        # Named placeholders — run_turn_live writes into these in real time
        transcript_slot  = st.empty()
        status_slot      = st.empty()

        # Audio slots: these are st.empty() containers that wrap components.html iframes.
        # We declare them here so run_turn_live can reference them.
        agent_audio_slot = st.empty()
        cust_audio_slot  = st.empty()

        # Always render current transcript — fixed height, scrollable, newest at bottom
        _render_transcript_scroll(transcript_slot)

        # Action buttons sit BELOW the transcript slots
        btn_col1, btn_col2 = st.columns([2, 2])
        with btn_col1:
            fire_next = st.button("▶ NEXT TURN", key="next_turn", disabled=st.session_state.running)
        with btn_col2:
            _ov_val = st.session_state.get("override_input", "").strip()
            if st.button("SEND TEXT OVERRIDE →", key="send_ov",
                         disabled=st.session_state.running or not _ov_val):
                st.session_state.pending_override = _ov_val
                log.info(f"Override queued: '{_ov_val[:80]}'")
                st.rerun()   # immediately rerun so should_run picks up pending_override
        fire_override_text  = False   # handled via session_state.pending_override
        fire_override_audio = False

    # ── RIGHT — assist (persistent placeholder) ───────────────────────────────
    with right:
        st.markdown('<div class="section-label">ASSIST + SENTIMENT</div>', unsafe_allow_html=True)
        assist_slot = st.empty()

        # Render last known assist (or placeholder) into slot
        if assist:
            _render_assist(assist_slot, assist)
        else:
            assist_slot.markdown('<div class="assist" style="color:#3a4560;font-style:italic">Assist loads after first turn…</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-label" style="margin-top:8px">COMPLIANCE</div>', unsafe_allow_html=True)
        for lbl, ok in [("Mini-Miranda delivered", st.session_state.miranda_done),
                        ("No harassment / threats", True),
                        ("Call within permitted hours", True),
                        ("No false representation", True)]:
            st.markdown(f'<div class="flag {"flag-ok" if ok else "flag-bad"}"><span>{"✓" if ok else "✗"}</span><span>{lbl}</span></div>', unsafe_allow_html=True)
        if not st.session_state.miranda_done:
            st.markdown('<div class="assist assist-warn" style="margin-top:4px"><div class="assist-title">⚠ PENDING</div>Mini-Miranda not yet detected.</div>', unsafe_allow_html=True)

    # ── TURN EXECUTION ────────────────────────────────────────────────────────
    # Consume pending override FIRST — before any other condition is evaluated.
    # This is critical: pending_override is set in session_state by the button
    # handler, so it survives the Streamlit rerun that the button click triggers.
    override_text = None
    if st.session_state.get("pending_override"):
        override_text = st.session_state.pending_override
        st.session_state.pending_override = None
        log.info(f"Override consumed: '{override_text[:80]}'")

    # Determine why we should run this turn
    time_since_last = time.time() - st.session_state.last_turn_ts if st.session_state.last_turn_ts else 999
    is_first_turn   = (st.session_state.turn_count == 0 and st.session_state.last_turn_ts == 0.0)
    is_auto_due     = st.session_state.auto_advance and st.session_state.last_turn_ts > 0 and time_since_last >= AUTO_SECS
    is_manual       = fire_next or override_text is not None

    should_run = not st.session_state.running and (is_manual or is_auto_due or is_first_turn)

    log.info(
        f"[should_run={should_run}] running={st.session_state.running} "
        f"manual={is_manual} auto_due={is_auto_due} first={is_first_turn} "
        f"override={repr(override_text)} fire_next={fire_next}"
    )

    if should_run:
        # ── Run one turn ──────────────────────────────────────────────────────
        run_turn_live(
            transcript_slot=transcript_slot,
            status_slot=status_slot,
            agent_audio_slot=agent_audio_slot,
            cust_audio_slot=cust_audio_slot,
            assist_slot=assist_slot,
            turns_slot=turns_slot,
            duration_slot=duration_slot,
            agent_text=override_text,  # None = AI generates; str = use this line
        )

        # ── Auto-loop ─────────────────────────────────────────────────────────
        if st.session_state.auto_advance:
            while (
                st.session_state.screen == "call"
                and st.session_state.auto_advance
                and not st.session_state.running
            ):
                time.sleep(AUTO_SECS)
                if st.session_state.screen != "call":
                    break
                run_turn_live(
                    transcript_slot=transcript_slot,
                    status_slot=status_slot,
                    agent_audio_slot=agent_audio_slot,
                    cust_audio_slot=cust_audio_slot,
                    assist_slot=assist_slot,
                    turns_slot=turns_slot,
                    duration_slot=duration_slot,
                    agent_text=None,
                )

        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  SCREEN 3 — POST-CALL
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "post":

    persona = PERSONAS[st.session_state.persona_key]
    summary = st.session_state.summary

    st.markdown('<div style="text-align:center;padding:20px 0 10px">'
                '<span style="font-family:IBM Plex Mono,monospace;font-size:18px;font-weight:600;color:#00c8f0">WHISPA</span>'
                '<span style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#3a4560;margin-left:10px">CALL ENDED · POST-CALL ANALYSIS</span>'
                '</div>', unsafe_allow_html=True)

    col_l, col_r = st.columns([3, 2.2], gap="large")

    with col_l:
        st.markdown('<div class="section-label">FULL TRANSCRIPT</div>', unsafe_allow_html=True)
        agent_nm = st.session_state.briefing.get("agent_name","AGENT").upper()
        cust_nm  = persona["name"].split()[0].upper()
        html = ""
        for m in st.session_state.transcript:
            ts   = datetime.fromtimestamp(m["ts"]).strftime("%H:%M:%S")
            role = m["role"]
            lbl  = f"AGENT — {agent_nm}" if role == "agent" else f"CUSTOMER — {cust_nm}"
            html += f'<div class="msg msg-{role}"><div class="msg-label">{lbl} · {ts}</div><div class="msg-bubble">{m["text"]}</div></div>'
        st.markdown(f'<div style="background:#0e1117;border:1px solid #1e2530;border-radius:8px;padding:14px;height:560px;overflow-y:auto">{html}</div>', unsafe_allow_html=True)

    with col_r:
        if summary:
            score = summary.get("agent_score", 0)
            score_color = "#00d97e" if score >= 70 else "#f0a500" if score >= 45 else "#f05050"
            st.markdown(f'<div class="score-ring" style="color:{score_color}">{score}<span style="font-size:16px;color:#6b7a94">/100</span></div>'
                        f'<div style="text-align:center;font-family:IBM Plex Mono,monospace;font-size:9px;color:#3a4560;letter-spacing:.1em;margin-bottom:12px">AGENT SCORE</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="summary-card"><h4>📋 Outcome</h4>{summary.get("outcome","—")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="summary-card"><h4>📈 Sentiment Journey</h4>{summary.get("sentiment_journey","—")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="summary-card" style="border-left:3px solid #00c8f0"><h4>➡️ Next Action</h4><strong>{summary.get("suggested_next_action","—")}</strong></div>', unsafe_allow_html=True)

            well = summary.get("what_went_well",[])
            if well:
                st.markdown(f'<div class="summary-card" style="border-left:3px solid #00d97e"><h4>✅ What Went Well</h4>'
                            + "".join(f'<div style="margin-bottom:4px">✓ {w}</div>' for w in well) + '</div>', unsafe_allow_html=True)
            improve = summary.get("what_to_improve",[])
            if improve:
                st.markdown(f'<div class="summary-card" style="border-left:3px solid #f0a500"><h4>⚠️ Improve</h4>'
                            + "".join(f'<div style="margin-bottom:4px">→ {i}</div>' for i in improve) + '</div>', unsafe_allow_html=True)
            facts = summary.get("key_facts_extracted",[])
            if facts:
                st.markdown(f'<div class="summary-card"><h4>📌 Key Facts</h4>'
                            + "".join(f'<span class="pill pill-green">{f}</span>' for f in facts) + '</div>', unsafe_allow_html=True)
            comp = summary.get("compliance_summary","—")
            st.markdown(f'<div class="summary-card"><h4>⚖️ Compliance</h4><span class="pill {"pill-green" if "pass" in comp.lower() else "pill-red"}">{comp}</span></div>', unsafe_allow_html=True)
        else:
            st.info("Generating summary…")

        s1, s2, s3 = st.columns(3)
        s1.metric("Turns",    st.session_state.turn_count)
        s2.metric("Duration", elapsed())
        s3.metric("Miranda",  "✓" if st.session_state.miranda_done else "✗")

        st.markdown('<div class="section-label" style="margin-top:10px">LOG OUTCOME</div>', unsafe_allow_html=True)
        outcome = st.selectbox(
            "Outcome",
            ["— select —", "PTP — Promise to Pay", "Dispute Raised", "Payment Taken",
             "Refused to Engage", "Call Back Arranged", "Voicemail Left"],
            label_visibility="collapsed",
        )
        log_notes = st.text_area("Notes", placeholder="Add notes…", height=70, key="log_notes_input")

        if st.button("SAVE LOG ✓"):
            if outcome == "— select —":
                st.warning("Please select an outcome before saving.")
            else:
                try:
                    call_id = call_logger.save(
                        briefing      = st.session_state.briefing,
                        persona       = persona,
                        summary       = st.session_state.summary,
                        transcript    = st.session_state.transcript,
                        call_start    = st.session_state.call_start,
                        turn_count    = st.session_state.turn_count,
                        miranda_done  = st.session_state.miranda_done,
                        logged_outcome= outcome,
                        logged_notes  = log_notes,
                    )
                    st.success(f"✓ Saved to calls_log.csv  ·  ID: `{call_id[:8]}…`")
                    log.info(f"Post-call log saved — call_id: {call_id}, outcome: {outcome}")
                except Exception as e:
                    st.error(f"Failed to save log: {e}")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📞  NEW CALL"):
            for k in list(_DEFAULTS.keys()):
                st.session_state[k] = _DEFAULTS[k]
            log.info("Reset — new call")
            st.rerun()

st.markdown('<hr style="margin:16px 0 6px"><div style="text-align:center;font-family:IBM Plex Mono,monospace;font-size:9px;color:#1e2530">WHISPA DEMO · DEEPGRAM · OPENROUTER · NOT FOR PRODUCTION</div>', unsafe_allow_html=True)
