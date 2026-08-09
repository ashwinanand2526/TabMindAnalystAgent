# Tab Researcher Agent — Graph-Based Multi-Agent System

A browser-tab comparison engine built on a **growing-graph multi-agent orchestrator**. Pick any open Chrome tabs, hit Analyse, and the agent fans out across them in parallel — extracting product specs, pricing, user reviews, and ratings — then compares, scores, and delivers a clear verdict with reasoning.

---

## Architecture Overview

┌──────────────────────────────────────────────────────────────────────────────┐
│  Chrome Extension (Phase 2 — fully implemented)                               │
│  popup.html · background.js · popup.js · popup.css                           │
│        │  POST /analyze-tabs  (tab URLs + scraped HTML)                      │
│        └──────────────────────────────────────────────┬──────────────────────┘
│                                                       │ (Auto-start via
│                                                       ▼  Native Messaging)
│ ┌────────────────────────────────────────────────────────────────────────────┐
│ │  extension_bridge.py  (FastAPI · localhost:7861)                           │
│ │  POST /analyze-tabs · GET /stream/{sid} (SSE) · GET /result/{sid}          │
│ │        │  fires Executor.run(query)                                        │
│ └────────┼───────────────────────────────────────────────────────────────────┘
│          │
│          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Growing-Graph Orchestrator  (flow.py)                                       │
│                                                                              │
│  [planner]                                                                   │
│      ├─► [tab_reader₁] ──► [distiller₁] ──► [critic₁] ─┐                  │
│      ├─► [tab_reader₂] ──► [distiller₂] ──► [critic₂] ──┼─► [comparator]  │
│      └─► [tab_reader₃] ──► [distiller₃] ──► [critic₃] ─┘        │         │
│                                                               [verdict]      │
│                                                               [formatter]    │
└──────────────────────────────────────────────────────────────────────────────┘
         │  POST /v1/chat (per skill)
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  LLM Gateway V8  (gateway/main.py · localhost:8108)                         │
│  Router pool (TINY/LARGE tier) · Worker pool (7 providers)                  │
│  Ollama · Gemini · Groq · Cerebras · NVIDIA · OpenRouter · GitHub Models    │
└──────────────────────────────────────────────────────────────────────────────┘

### Key Concepts

| Concept | What it means |
|---------|--------------|
| **Growing graph** | The DAG is not fixed upfront. Every skill can emit successor nodes at runtime; the Planner can be re-invoked on failure. |
| **Fan-out / fan-in** | One `tab_reader → distiller` chain runs per tab in parallel. The `comparator` waits for all of them before firing. |
| **Critic auto-insertion** | Any skill marked `critic: true` in `agent_config.yaml` (currently `distiller`) gets a Critic node automatically inserted on every outgoing edge. A `fail` verdict splices a recovery Planner into the graph. |
| **Tool-use via MCP** | Skills that need the web (`researcher`, `retriever`) call tools through the MCP stdio server (`mcp_server.py`). The Critic, Distiller, Comparator, and Verdict never call tools — they reason over what's already in the prompt. |
| **Session persistence** | Every run writes `graph.pkl` + per-node JSON to `code/state/sessions/<sid>/`. Resume with `--resume <sid>`. |

### Skill Catalogue

| Skill | Role | Tools |
|-------|------|-------|
| `planner` | Decomposes query into DAG; re-plans on failure | none |
| `researcher` | Fetches web content | `web_search`, `fetch_url` |
| `retriever` | Vector search over indexed knowledge | `search_knowledge` |
| `distiller` | Extracts structured fields from raw text | none |
| `critic` | Pass / fail evaluation of an upstream node | none |
| `summariser` | Condenses long content | none |
| `formatter` | Renders the final user-facing answer | none |
| `coder` | Emits Python; sandbox runs it inline | none |
| `tab_reader` | Parses pre-fetched tab HTML into a product record | none |
| `comparator` | Builds a scored comparison matrix from N tab records | none |
| `verdict` | Applies user focus weights; picks winner + rationale | none |

---

## Repository Layout

```
TabResearcher-GraphBased/
│
├── README.md                    ← you are here
├── README-orig.md               ← original session scaffolding notes
├── .env                         ← API keys (never commit)
├── query.txt                    ← sample run commands (including Critic test queries)
│
├── code/                        ← agent — run everything from here
│   ├── flow.py                  ← orchestrator: Graph + Executor + CLI
│   ├── skills.py                ← skill registry, prompt rendering, run_skill()
│   ├── recovery.py              ← failure classification + critic-fail splice
│   ├── extension_bridge.py      ← FastAPI bridge (localhost:7861)
│   ├── agent_config.yaml        ← skills catalogue with per-skill temperature/tokens
│   ├── schemas.py               ← AgentResult, NodeSpec, NodeState, MemoryItem
│   ├── persistence.py           ← session writes (graph.pkl + per-node JSON)
│   ├── mcp_runner.py            ← multi-turn tool-use loop
│   ├── mcp_server.py            ← MCP tools: web_search, fetch_url, search_knowledge, …
│   ├── sandbox.py               ← subprocess Python runner for coder skill
│   ├── replay.py                ← stdin-driven trace viewer
│   ├── visualize_graph.py       ← renders dag.png at each executor step
│   ├── memory.py                ← FAISS-backed memory store
│   ├── vector_index.py          ← embedding + FAISS index management
│   ├── artifacts.py             ← binary artifact store
│   ├── gateway.py               ← thin client wrapper for the LLM gateway
│   ├── prompts/                 ← one .md per skill
│   │   ├── planner.md
│   │   ├── researcher.md
│   │   ├── distiller.md
│   │   ├── critic.md
│   │   ├── formatter.md
│   │   ├── tab_reader.md        ← NEW
│   │   ├── comparator.md        ← NEW
│   │   └── verdict.md           ← NEW
│   ├── state/sessions/          ← per-run persistence (auto-created)
│   ├── sandbox/                 ← coder skill working directory
│   └── tests/                   ← pytest suite
│
├── gateway/                     ← LLM Gateway V8 — treat as a service
│   ├── main.py                  ← FastAPI app (port 8108)
│   ├── providers.py             ← 7 provider adapters
│   ├── router.py                ← worker pool + router pool
│   ├── agent_routing.yaml       ← agent → preferred provider mapping
│   └── ...
│
└── extension/                   ← Chrome extension (Phase 2 — coming soon)
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | |
| [uv](https://docs.astral.sh/uv/) | `pip install uv` or `curl -Ls https://astral.sh/uv/install.sh \| sh` |
| Ollama | `winget install Ollama.Ollama` · then `ollama pull nomic-embed-text` |
| At least one LLM API key | Gemini free tier works for basic runs — see `.env` setup below |

---

## Setup

### 1 — Copy and fill in secrets

```bash
# from the repo root
cp .env.example .env
```

Open `.env` and add the keys you have. The minimum for a working run:

```env
# Required for the gateway to route requests:
GEMINI_API_KEY=your_key_here

# Required for web_search (Tavily is primary; DDG is the free fallback):
TAVILY_API_KEY=your_key_here          # optional but recommended

# Required for memory / vector search:
OLLAMA_URL=http://localhost:11434      # default; change if Ollama runs elsewhere
```

### 2 — Install dependencies

```bash
# Gateway
cd gateway && uv sync && cd ..

# Agent + bridge
cd code && uv sync && cd ..
```

### 3 — Start Ollama (for embeddings)

```bash
ollama serve          # if not already running as a service
ollama pull nomic-embed-text
```

---

## Running the Project

All commands below are run from the **`code/`** directory.

### Terminal 1 — Start the LLM Gateway

```bash
cd gateway
uv run python main.py
# Gateway starts on http://localhost:8108
# Check: curl http://localhost:8108/v1/routers
```

### Terminal 2 — Run the agent directly (CLI)

```bash
cd code

# Basic hello
uv run python flow.py "Say hello."

# Web research + parallel fan-out
uv run python flow.py "Find the populations of London, Paris, Berlin and tell me which two are closest in size."

# Resume a crashed session
uv run python flow.py --resume <session-id>

# Replay a session trace interactively
uv run python replay.py <session-id>
```

### Terminal 2 (alternative) — Start the Extension Bridge

```bash
cd code
uv run python extension_bridge.py
# Bridge starts on http://localhost:7861
# Check: curl http://localhost:7861/health
```

Then POST a comparison request:

```bash
curl -X POST http://localhost:7861/analyze-tabs \
  -H "Content-Type: application/json" \
  -d '{
    "tabs": [
      {
        "url": "https://amazon.com/dp/B0C6FXNFHQ",
        "title": "Sony WH-1000XM5",
        "html": "<h1>Sony WH-1000XM5</h1><span>$279</span><span>4.7 out of 5 stars</span><p>30hr battery, USB-C, best ANC on the market.</p>"
      },
      {
        "url": "https://amazon.com/dp/B098FKXT8L",
        "title": "Bose QuietComfort 45",
        "html": "<h1>Bose QC45</h1><span>$329</span><span>4.5 out of 5 stars</span><p>24hr battery, 3.5mm jack included, excellent comfort.</p>"
      }
    ],
    "focus": "balanced"
  }'
# Returns: {"session_id": "s8-xxxx", "status": "running"}

# Stream progress:
curl -N http://localhost:7861/stream/s8-xxxx

# Get final result:
curl http://localhost:7861/result/s8-xxxx
```

---

## Critic Test Queries

The Critic skill evaluates Distiller output for **internal consistency** (no tools needed). The queries below are designed to exercise both the pass and fail paths.

### Pass — 4-field extraction with lifespan check

The Distiller extracts `birth_year=1856`, `death_year=1943`. Lifespan = 87 years → Critic **passes**.

```bash
uv run python flow.py "Fetch the Wikipedia page for Nikola Tesla and extract exactly four fields: birth_year (integer), death_year (integer), birth_place (string), us_patents (string). Verify that death_year minus birth_year is between 30 and 120 years — if not, flag it as inconsistent."
```

### Fail → Planner recovery — 5-field extraction with date consistency check

The Wikipedia article contains an Old Style / New Style calendar note that can cause `birth_year ≠ year(birth_date)`. When the Critic detects this mismatch it emits `"verdict": "fail"`, the orchestrator skips the formatter, splices a recovery Planner into the graph, and a second Researcher + Distiller corrects the answer.

```bash
uv run python flow.py "Fetch the Wikipedia page for Nikola Tesla and extract exactly five fields: birth_year (integer), birth_date (full date string e.g. '10 July 1856'), death_year (integer), birth_place (string), us_patents (string). Critically verify that birth_year exactly equals the year component of birth_date — if they differ by even one year, that is an error and must be flagged."
```

Watch the console for:
```
↪ critic-fail recovery: planner node n:7 for n:3
```

---

## Comparison Dimensions (Dynamic)

The `tab_reader` skill infers a `detected_category` from each tab's content and proposes relevant dimensions. The `comparator` unions them across all tabs.

| Category | Example dimensions |
|----------|--------------------|
| Headphones | price · anc_quality · battery_life · weight · codec_support |
| Laptop | price · cpu_benchmark · ram_gb · storage_gb · display_nits · weight_kg |
| Hotel | price_per_night · star_rating · review_score · wifi_quality · location_score |
| Book | price · rating · page_count · author_credibility |
| Software | price_tier · rating · ease_of_use · feature_count · support_quality |

The `focus` parameter (`price` · `specs` · `reviews` · `balanced`) applies a 2× weight multiplier to the relevant dimensions in the `verdict` skill.

---

## Chrome Extension Setup (Phase 2)

The Chrome extension enables comparing open tabs in real-time. It includes a native installer to ensure the FastAPI bridge is automatically launched on your system.

### 1. Load the Extension into Chrome
1. Open Google Chrome and go to `chrome://extensions`.
2. Turn on **Developer mode** in the top right corner.
3. Click **Load unpacked** in the top left.
4. Select the `extension` folder in this repository root.
5. Copy the 32-character Extension ID generated for it (e.g., `kbomdfofehinmchibigldphfnhobgdpi`).

### 2. Configure and Register the Auto-Start Daemon (Windows Only)
The extension uses Chrome Native Messaging to check health and automatically start the Python `extension_bridge.py` backend if it is not running.
1. Open a terminal in the `extension` directory.
2. Run the registration batch script, passing your Extension ID as an argument:
   ```cmd
   .\register_native_host.bat YOUR_EXTENSION_ID
   ```
3. This dynamically builds `com.tabresearcher.bridge_launcher.json` with your local absolute path and creates the registry key under `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.tabresearcher.bridge_launcher`.

### 3. Using the Extension
1. Open any product pages you wish to compare (e.g., different headphone models or laptops on Amazon).
2. Click the **Tab Researcher** extension icon in your toolbar.
3. Check/select the tabs you want to include in the comparison.
4. Choose an **Analysis Focus** (Balanced, Price, Specs, or Reviews).
5. Click **Analyze Tabs**.
6. The extension will scrape the tab contents, start the agent, and connect to the live progress stream. You can watch the steps dynamically complete in the console logs.
7. Once finished, a structured comparison table with AI scoring and a text verdict will be rendered inline!

---

## Troubleshooting


| Symptom | Fix |
|---------|-----|
| `[gateway] failed to start within 45s` | Run `cd gateway && uv run python main.py` and read its stderr. Usually a missing API key or port 8108 already taken. |
| `httpx.HTTPStatusError: 503` | All provider workers are in cooldown. Add another key to `.env` or wait a minute. |
| `bridge import OK` but `/analyze-tabs` times out | Check the gateway is running on 8108. The bridge calls `ensure_gateway()` from `flow.py` on startup. |
| Critic always passes | Lower Distiller temperature (`temperature: 0.0` in `agent_config.yaml`) and re-run. Or use the 5-field Tesla query above. |
| Short / wrong final answer | Run `uv run python replay.py <sid>` and inspect the `prompt_sent` field of each node to see exactly what hit the gateway. |

---

## Running Tests

```bash
cd code
uv run pytest tests/ -v
```

---

## Environment Variables Reference

```env
# LLM providers (add any you have; gateway fails over automatically)
GEMINI_API_KEY=
GROQ_API_KEY=
CEREBRAS_API_KEY=
NVIDIA_API_KEY=
OPEN_ROUTER_API_KEY=
GITHUB_ACCESS_TOKEN=
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:31b            # optional local model

# Web search
TAVILY_API_KEY=                    # primary; DuckDuckGo is the free fallback

# Gateway
GATEWAY_V8_PORT=8108               # default

# Extension bridge
BRIDGE_PORT=7861                   # default
```
