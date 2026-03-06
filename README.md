# WHISPA — Live Call Simulator

> AI-powered debt collection training platform. Simulate live calls with realistic AI debtor personas, receive real-time agent coaching, review structured post-call analysis, and persist every call to a searchable log — all without touching a real customer.

---

## Table of Contents

1. [How to Run](#how-to-run)
2. [Architecture](#architecture)
3. [Screen Flow](#screen-flow)
4. [Data Flow Per Turn](#data-flow-per-turn)
5. [Agent-Assist Features](#agent-assist-features)
6. [Call Log](#call-log)
7. [Key Tradeoffs](#key-tradeoffs)
8. [How We Reduce Hallucinations](#how-we-reduce-hallucinations)
9. [What to Build Next](#what-to-build-next)
10. [File Reference](#file-reference)

---

## How to Run

### Prerequisites


- [Deepgram](https://deepgram.com) API key — for TTS (Aura-2) and STT (Nova-3)
- [OpenRouter](https://openrouter.ai) API key — for LLM access (Claude Sonnet)

### Installation

```bash
git clone <repo-url>
cd whispa
cd verfinal
pip install -r requirements.txt
```

### Environment

Create a `.env` file in the project root:

```env
DEEPGRAM_API_KEY=your_deepgram_key_here
OPENROUTER_API_KEY=your_openrouter_key_here
```

### Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. The call log (`calls_log.csv`) is created automatically on first save.

> **Note:** If the call screen shows no activity after starting, restart the app once with `Ctrl+C` then `streamlit run app.py` to clear any stale session state.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WHISPA  —  app.py                                  │
│                         Streamlit UI + Orchestration                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│   ┌─────────────┐     ┌──────────────────────────┐     ┌─────────────────┐  │
│   │  SCREEN 1   │────▶│       SCREEN 2           │────▶│   SCREEN 3      │  │
│   │  Briefing   │     │      Live Call           │     │  Post-Call      │  │
│   │             │     │                          │     │  Analysis       │  │
│   │ · Persona   │     │  run_turn_live()         │     │                 │  │
│   │ · Agent     │     │  ┌──────────────────┐    │     │ · Score         │  │
│   │   name      │     │  │ 1. ai_agent.py   │    │     │ · Summary       │  │
│   │ · Goal      │     │  │    LLM → line    │    │     │ · Transcript    │  │
│   │ · Tone      │     │  │ 2. TTS → iframe  │    │     │ · Coaching      │  │
│   │ · Discount  │     │  │ 3. ai_customer   │    │     │ · Save Log      │  │
│   │ · Notes     │     │  │    LLM → reply   │    │     │                 │  │
│   └─────────────┘     │  │    [CALL_ENDED]? │    │     └────────┬────────┘  │
│                        │  │ 4. TTS → iframe  │    │              │           │
│                        │  │ 5. agent_assist  │    │              ▼           │
│                        │  │    → JSON        │    │     call_logger.py       │
│                        │  └──────────────────┘    │     calls_log.csv        │
│                        │                          │                           │
│                        │  st.empty() placeholders │                           │
│                        │  stream updates live     │                           │
│                        │  without full rerun      │                           │
│                        └──────────────────────────┘                           │
│                                                                               │
├───────────────────────────────────────────────────────────────────────────── │
│  SUPPORTING MODULES                                                           │
│                                                                               │
│  prompts.py          All personas, briefing-aware prompt builders,            │
│                      hardcoded FDCPA compliance rules                         │
│                                                                               │
│  text_to_speech.py   Deepgram Aura-2 REST → base64 MP3                       │
│  speech_to_text.py   Deepgram Nova-3 REST (file) + WS (live stream class)    │
│  call_summary.py     Post-call LLM analysis → structured JSON + score        │
│  logger.py           Structured console logging with turn dividers            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### External Services

```
┌──────────────┐        ┌─────────────────────────────────────────┐
│   Browser    │        │              OpenRouter                  │
│              │◀──────▶│   claude-sonnet-4-5                      │
│  Streamlit   │        │   · ai_agent    (agent turn)             │
│  iframe TTS  │        │   · ai_customer (customer reply)         │
│  audio plays │        │   · agent_assist (real-time coaching)    │
└──────────────┘        │   · call_summary (post-call score)       │
                        └─────────────────────────────────────────┘

                        ┌─────────────────────────────────────────┐
                        │              Deepgram                    │
                        │   Aura-2   → TTS  (agent + customer)    │
                        │   Nova-3   → STT  (file upload)         │
                        └─────────────────────────────────────────┘
```

---


---

## Data Flow Per Turn

Each turn inside `run_turn_live()` executes these steps sequentially, writing into `st.empty()` placeholders so the browser updates live without a full page rerun:

```
  ┌─────────────────────────────────────────────────────────┐
  │  run_turn_live()                                         │
  │                                                          │
  │  1. ┌─────────────────────────────────────────────┐     │
  │     │ ai_agent.get_next_line()                    │     │
  │     │ · Reads: full transcript + briefing         │     │
  │     │ · Model: claude-sonnet-4-5 (temp 0.7)       │     │
  │     │ · Output: spoken agent line (no stage dirs) │     │
  │     └──────────────────────┬──────────────────────┘     │
  │                            │ agent_text                  │
  │  2.                        ▼                             │
  │     ┌─────────────────────────────────────────────┐     │
  │     │ text_to_speech.synthesise_agent()           │     │
  │     │ · Deepgram Aura-2 REST → base64 MP3         │     │
  │     │ · Rendered into browser via iframe          │     │
  │     │ · audio.load() + play() on every turn       │     │
  │     │ · Sleep: word_count ÷ 150wpm + 0.8s buffer  │     │
  │     └──────────────────────┬──────────────────────┘     │
  │                            │                             │
  │  3.                        ▼                             │
  │     ┌─────────────────────────────────────────────┐     │
  │     │ ai_customer.get_reply()                     │     │
  │     │ · Reads: transcript + agent_text            │     │
  │     │ · Model: claude-sonnet-4-5                  │     │
  │     │ · Output: spoken reply or [CALL_ENDED] ...  │     │
  │     │ · Post-process: strip sentinel + stage dirs │     │
  │     └──────────────────────┬──────────────────────┘     │
  │                            │ customer_reply              │
  │                            ├──── [CALL_ENDED]? ──────▶ end call + summary │
  │  4.                        ▼                             │
  │     ┌─────────────────────────────────────────────┐     │
  │     │ text_to_speech.synthesise()                 │     │
  │     │ · Persona-matched voice (Deepgram Aura-2)   │     │
  │     │ · Same iframe pattern as agent audio        │     │
  │     └──────────────────────┬──────────────────────┘     │
  │                            │                             │
  │  5.                        ▼                             │
  │     ┌─────────────────────────────────────────────┐     │
  │     │ agent_assist.analyse()                      │     │
  │     │ · Reads: transcript + briefing + persona    │     │
  │     │ · Returns JSON: sentiment, stage, coaching, │     │
  │     │   script_line, compliance_alerts, signals   │     │
  │     │ · Updates assist panel + top-bar stats      │     │
  │     └─────────────────────────────────────────────┘     │
  │                                                          │
  │  → turn_count += 1  →  auto-loop sleeps AUTO_SECS       │
  └─────────────────────────────────────────────────────────┘
```

---

## Agent-Assist Features

### Real-time sentiment tracking
Live sentiment score (0–100) with colour-coded bar: hostile (red) → frustrated (amber) → neutral (grey) → cooperative (green) → distressed (purple). Updates every turn.

**Why:** Agents lose track of sentiment shifts under pressure. A visible score gives them permission to switch from defence mode to resolution mode at the right moment.

### Call stage detection
Identifies the active phase: `Opening → Rapport → Negotiation → Objection Handling → Resolution → Closing`. Displayed as a badge that updates each turn.

**Why:** Inexperienced agents jump straight to negotiation before rapport, causing hostility spikes. The stage badge reminds them to follow the natural call progression.

### Briefing-aware coaching + scripted suggestion
Two outputs every turn: a short coaching note tied to the agent's stated goal/tone, and a verbatim line they could say next within their authorised authority.

**Why:** Generic coaching ("be empathetic") is useless without context. Briefing-aware suggestions are immediately actionable — an assertive-briefed agent gets different guidance than an empathetic one.

### Compliance alerts
Flags FDCPA violations in real time: threatening language, misrepresentation, failing to identify as a debt collection call, or exceeding the agent's discount ceiling.

**Why:** FDCPA violations carry serious legal liability. Catching them during training prevents bad habits reaching live customers.

### Mini-Miranda tracker
Dedicated compliance panel tracks whether the Mini-Miranda was delivered. Red warning + #1 priority coaching note until confirmed. Turns green on detection.

**Why:** The Mini-Miranda is legally required on first contact and most commonly forgotten when the agent is flustered by a hostile opener.
### Payment Plan Calculator (💳 Payment Options)
When negotiation begins, the assist system automatically calculates repayment options based on the debt balance:

- **Option A:** Balance ÷ 6 months  
- **Option B:** Balance ÷ 12 months  
- **Settlement:** Balance with authorised discount (if allowed)

Hidden during early stages and only shown when relevant. Settlement row highlighted in green.

**Why:** Removes manual calculations and helps agents present clear payment choices instantly.


### Escalation & Opportunity Signals
The system scans the transcript and shows signal cards when evidence appears:

- 🚨 **Dispute detected** – customer denies or questions debt  
- 💰 **Settlement opportunity** – customer mentions lump sum or discounts  
- ❤️ **Financial hardship** – illness, job loss, bereavement  
- ⚖️ **Legal threat raised** – solicitor, court, legal action  
- 👥 **Third party involved** – charity, IVA, bankruptcy

Signals appear **only when supported by the transcript**.

**Why:** Highlights risk situations and negotiation opportunities instantly.

---


### Post-call scoring (briefing-aware)
Agent scored 0–100 against their actual stated goal and constraints — not generic benchmarks. Capped at 60 if goal not achieved. Auto-FAIL if discount ceiling was exceeded.

**Why:** Scores must be fair and goal-specific. The same outcome achieved the wrong way should score differently.



## Key Tradeoffs

### Synchronous turn loop vs. async/WebSocket
Turns run synchronously inside a single Streamlit execution using `st.empty()` placeholders. Simpler and more debuggable than WebSocket, but holds a server thread for the call duration.

**Accepted:** Appropriate for a single-user training tool. Multi-user production would need Celery, RQ, or asyncio.

### `components.html()` iframe audio vs. `st.audio()`
Audio rendered as iframes so `audio.play()` fires reliably on every turn — each iframe is a fresh DOM document, bypassing Streamlit's virtual-DOM diffing that would otherwise skip autoplay on repeated renders.

**Accepted:** ~100ms iframe mount overhead is imperceptible vs. the reliability gain.

### LLM sentiment vs. dedicated classifier
Sentiment runs through the same `claude-sonnet-4-5` as the assist — slower (~1–2s) but contextually richer than a lightweight classifier for debt-collection-specific language.

**Accepted:** Delay is imperceptible in a training context. Production would run a lighter model in parallel.

### Single model for all roles
Agent, customer, and assist all use `claude-sonnet-4-5`. Risk of stylistic convergence between agent and customer voices over long calls.

**Accepted:** Simplicity over complexity for a demo. Production would separate providers per role.

### Word-rate sleep vs. true playback completion
Python estimates audio duration (words ÷ 150 wpm + 0.8s) and sleeps. Cannot receive a "playback complete" event from the browser iframe without a custom bidirectional component.

**Accepted:** Estimate is accurate enough for training use.

### Append-only CSV vs. database
Zero infrastructure — no setup required. Doesn't support concurrent writes or indexed queries.

**Accepted:** CSV schema is designed for direct migration to SQLite/Postgres by replacing only the `csv.DictWriter` block in `call_logger.py`.

---

## How We Reduce Hallucinations

**Constrained factual scope** — every prompt lists exactly what facts the model may reference. Both agent and customer are explicitly told not to invent account details, addresses, or payment history beyond what is provided.

**Structured JSON outputs** — assist and summary prompts request a typed JSON schema. Code strips markdown fences before parsing and falls back to a safe default dict on failure — the UI never crashes.

**Briefing-grounded scoring** — summary scoring criteria are derived from the agent's actual briefing, preventing the model from praising outcomes that contradict the stated goal.

**Transcript-only grounding** — the assist prompt explicitly states: *"Never invent facts the transcript does not contain."* Prevents hallucinating admissions or promises that weren't made.

**Output format policing** — customer and agent prompts contain prominent, repeated rules: no stage directions, no asterisks, no narration, no internal notes. Prominence and repetition are more reliable than single-line mentions.

**Sentinel hardening** — `[CALL_ENDED]` is precisely specified with an example. `ai_customer.py` post-processes every reply: scans all lines for the sentinel, strips residual `*hangs up*` text with regex, stores only clean spoken words.

**Temperature control** — agent LLM at `temperature=0.7` (human variation, instruction-following). Assist and summary at default (near 0) for consistent structured output.

---

## What to Build Next

**1. Agent  persona builder**
Different agents to deal with different customers based on their previous records ie firm agents, kind agents.

**2. Longitudinal scoring dashboard**
Query `calls_log.csv` to surface per-agent trends across sessions: compliance improving, empathy flat, average score by persona type. Generate weekly coaching reports automatically. The CSV schema is already structured for this.


**3. Proper FDCPA compliance rule engine**
Replace keyword-based Mini-Miranda detection with a structured rule engine: timezone-aware permitted-hour checking, implied legal threat detection via semantic similarity, third-party disclosure detection, cease-communication flag tracking. This can be done with set of instructions that will be loaded with each ai agents. 

**4. Async parallel LLM calls**
Run assist analysis concurrently with customer TTS synthesis rather than sequentially. Saves ~1–2s per turn — meaningful across a 10-turn call.Also this helps to create summary and insights faster also we can call another llm call to raise an issue to the superviser or another call to llm to fact check with database about credits recieved or not 

**5. Prebuilt scenario cases**
The agent has an access to a vector db with previous case files on how it dealt with certain type of customers, what language  what script it used and use that as an example and guide to deal with new customers. This can also help a clear path on how to direct the call based on sitatuation rather that general one  

**6. Domain Knowledge**
Vector Databae of domain knowledge and set of instructions that needs to be followed by agents
---

