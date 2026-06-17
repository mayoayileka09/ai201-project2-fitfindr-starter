# FitFindr 🛍️

FitFindr is an AI shopping agent for secondhand fashion. You describe what you want in plain
English, and a three-tool planning loop finds a matching listing, styles it against your own
wardrobe, and writes a shareable "fit card" caption for the look.

```
User query
   │
   ▼
run_agent()  ──►  search_listings  ──►  suggest_outfit  ──►  create_fit_card
 (agent.py)         (Tool 1)              (Tool 2)             (Tool 3)
   │                                                              │
   └────────────────────── session dict (shared state) ──────────┘
```

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Python 3.10+ required
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

> **Note:** the code uses `str | None` type hints (PEP 604) and so requires **Python 3.10+**.
> Tools 2 and 3 call Groq's `llama-3.3-70b-versatile`, so `GROQ_API_KEY` must be set for them.

## Running it

```bash
python app.py        # launch the Gradio UI (http://localhost:7860)
python agent.py      # run the CLI demo (happy path + no-results path)
pytest tests/        # run the tool test suite
```

## Project layout

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/data_loader.py       # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
├── tools.py                   # the 3 tools: search_listings, suggest_outfit, create_fit_card
├── agent.py                   # run_agent() planning loop + query parser + session state
├── app.py                     # Gradio UI (handle_query maps the session to 3 panels)
├── tests/test_tools.py        # pytest tests, one per tool + one per failure mode
└── planning.md                # design doc (spec, planning loop, architecture)
```

---

## Tool Inventory

The documented signatures below match the actual function definitions in `tools.py`.

### Tool 1 — `search_listings`

```python
search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]
```

- **Inputs:**
  - `description` (`str`) — free-text keywords describing the wanted item (e.g. `"vintage graphic tee"`).
  - `size` (`str | None`) — size to filter by; case-insensitive **substring** match, so `"M"` matches `"S/M"` and `"M/L"`. `None` skips size filtering.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips price filtering.
- **Output:** `list[dict]` — full listing dicts, sorted by descending keyword-overlap relevance (best match first). Each dict has `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Returns `[]` when nothing matches.
- **Purpose:** Find the secondhand items that match the user's request and rank them by relevance. This is the only tool that touches the dataset (`load_listings()`).

### Tool 2 — `suggest_outfit`

```python
suggest_outfit(new_item: dict, wardrobe: dict) -> str
```

- **Inputs:**
  - `new_item` (`dict`) — the selected listing dict (the top result from Tool 1).
  - `wardrobe` (`dict`) — a wardrobe shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. May be empty.
- **Output:** `str` — a non-empty styling suggestion (1–2 outfits). When the wardrobe has items it names specific pieces; when empty it returns general styling advice for the item.
- **Purpose:** Style the found item against what the user already owns, using the LLM (`llama-3.3-70b-versatile`, temperature 0.7).

### Tool 3 — `create_fit_card`

```python
create_fit_card(outfit: str, new_item: dict) -> str
```

- **Inputs:**
  - `outfit` (`str`) — the styling text returned by `suggest_outfit`.
  - `new_item` (`dict`) — the listing dict, used so the caption can name the item, price, and platform.
- **Output:** `str` — a 2–4 sentence casual social caption (Instagram/TikTok OOTD style). Generated at temperature 1.0 so repeat calls vary.
- **Purpose:** Turn the outfit into something postable. If `outfit` is empty/whitespace it returns a descriptive error string instead of calling the LLM.

### Orchestrator — `run_agent` (in `agent.py`)

```python
run_agent(query: str, wardrobe: dict) -> dict
```

Runs one full interaction and returns the completed **session dict** (see State Management). Callers check `session["error"]` first; if it is `None`, `outfit_suggestion` and `fit_card` are populated.

---

## How the Planning Loop Works

`run_agent()` is a fixed linear pipeline with **one conditional branch** — it is not an unconditional "call all three tools every time" sequence. The branch is what makes the agent's behavior change with its inputs.

1. **Init** — build a fresh `session` dict via `_new_session(query, wardrobe)`.
2. **Parse** — `_parse_query()` extracts `description`, `size`, and `max_price` from the raw query using regex (e.g. `under $30` → `max_price=30.0`, `size M`/standalone `M` → `size="M"`, with those phrases stripped out of the description). Stored in `session["parsed"]`.
3. **Search (the branch point)** — call `search_listings(**parsed)` and store the list in `session["search_results"]`.
   - **If the list is empty:** set a specific `session["error"]` message (naming the query and offering concrete fixes) and **`return` immediately**. `suggest_outfit` and `create_fit_card` are never called.
   - **If the list is non-empty:** continue.
4. **Select** — `session["selected_item"] = search_results[0]` (top-ranked).
5. **Suggest** — call `suggest_outfit(selected_item, wardrobe)`; store in `session["outfit_suggestion"]`.
6. **Fit card** — call `create_fit_card(outfit_suggestion, selected_item)`; store in `session["fit_card"]`.
7. **Return** — `error` stays `None` on the happy path.

**Termination:** the loop always ends by returning the session — either early at step 3 (with `error` set, downstream fields `None`) or after step 6 (all result fields populated). There is no looping/retrying; success is implied by `error is None`.

---

## State Management

All state for a single interaction lives in **one `session` dict** created by `_new_session()`. Tools are pure functions (explicit args in, value out); the planning loop is the only thing that reads from and writes to the session, so each `run_agent()` call is independent — nothing is stored in globals.

| Field | Type | Written when | Read by |
|-------|------|--------------|---------|
| `query` | `str` | at init | parse step |
| `parsed` | `dict` (`description`, `size`, `max_price`) | step 2 | `search_listings` args |
| `wardrobe` | `dict` | at init (from UI radio) | `suggest_outfit` arg |
| `search_results` | `list[dict]` | step 3 | empty-check + select |
| `selected_item` | `dict` | step 4 | `suggest_outfit`, `create_fit_card` |
| `outfit_suggestion` | `str` | step 5 | `create_fit_card`, UI panel 2 |
| `fit_card` | `str` | step 6 | UI panel 3 |
| `error` | `str \| None` | error branch | checked first by `handle_query` |

**Flow:** `query → parsed → search_results → selected_item → outfit_suggestion → fit_card`. Each tool's output becomes the next tool's input — the *same* `selected_item` dict object is handed to both Tool 2 and Tool 3, and the *same* `outfit_suggestion` string is handed to Tool 3 (verified by object-identity checks during testing). In `app.py`, `handle_query()` builds the wardrobe from the radio choice, calls `run_agent()`, then maps the returned session onto the three output panels (or shows `error` in panel 1 and blanks the other two).

---

## Error Handling Strategy

Every tool degrades gracefully — it returns a value rather than raising — and the loop branches on those values.

| Tool | Failure mode | Strategy | Concrete example from testing |
|------|--------------|----------|-------------------------------|
| `search_listings` | No listing matches the filters | Return `[]` (never raise). The loop detects the empty list and sets a specific `error` naming the query + offering fixes, then returns early **without** calling the other tools. | `search_listings('designer ballgown', size='XXS', max_price=5)` → `[]`. Full agent → `error = "No listings matched 'designer ballgown' size XXS under $5. Try raising your max price, dropping the size filter, using broader keywords."`, and `suggest_outfit`/`create_fit_card` were called **0 times**, leaving `fit_card = None`. |
| `suggest_outfit` | Wardrobe is empty (new user) | Treated as a normal branch, not an error — return general styling advice for the item. (LLM call errors fall back to a brief styling line so the run still completes.) | `suggest_outfit(<Y2K Baby Tee>, get_empty_wardrobe())` → a useful non-empty string of general advice ("...pairs perfectly with flowy skirts or distressed denim...") instead of a crash or `""`. |
| `create_fit_card` | `outfit` is empty/whitespace | Guard before the LLM call; return a descriptive message string. | `create_fit_card('', <listing>)` → `"Couldn't generate a fit card because no outfit suggestion was available."` (no exception). |

These three cases are covered by `tests/test_tools.py` (`test_search_empty_results`, `test_suggest_outfit_empty_wardrobe_does_not_crash`, `test_create_fit_card_empty_outfit_returns_message`). A consolidated capture of all three triggered failures is saved in `FAILURE_MODES.txt`.

---

## Spec Reflection

- **Where the spec helped:** Writing the *Planning Loop* and *State Management* sections of `planning.md` before coding made the single conditional branch explicit — "if `search_results` is empty, set `error` and return early; otherwise select `results[0]` and continue." Because the early-exit was designed up front, the no-results path worked on the first run and the downstream tools were never accidentally called with empty input. The session-field table in the spec mapped almost one-to-one onto `_new_session()`.

- **Where implementation diverged, and why:** The spec described query parsing as a step inside `run_agent`. In code I pulled it into a dedicated `_parse_query()` helper instead. The reason: parsing is the one piece of pure, deterministic logic that benefits from being unit-tested and inspected on its own (and printed during the demo), so isolating it kept the planning loop readable and made the parsing rules verifiable independently of the tools. The behavior is identical to the spec — only the structure changed.

---

## AI Usage

- **Implementing `search_listings` from the spec.** I gave the AI the Tool 1 block from `planning.md` (inputs, return value, failure mode) and the existing docstring, and asked it to implement the function using `load_listings()`. I reviewed the output before trusting it and **overrode the relevance scoring**: the first version did exact full-string matching, which missed partial keyword overlaps. I revised it to tokenize the description and score by per-keyword overlap across `title`/`description`/`category`/`style_tags`, dropping score-0 items and sorting descending. I then confirmed it against three queries (a match, a price-filtered query, and the impossible query returning `[]`).

- **Wiring `handle_query` in `app.py`.** I directed the AI to map the returned session dict onto the three Gradio panels following the numbered TODO. I **revised the error handling** so that when `session["error"]` is set, the message goes to panel 1 and panels 2–3 are returned blank (rather than showing stale or empty placeholder text), and I added the empty-query guard before calling `run_agent()` so a blank submission never starts a run. I verified all three paths (empty query, no-results, happy path) by calling `handle_query()` directly before launching the UI.

- **Environment fix (caught and overridden).** The AI initially tried to `pip install -r requirements.txt` into the provided `.venv`, which was Python 3.9. I overrode this after the install failed — the code's `str | None` hints require 3.10+ — and recreated the venv with Python 3.13 before installing, which is why the README now documents the 3.10+ requirement.

---

## The Data

- `data/listings.json` — 40 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, …). Fields: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`.
- `data/wardrobe_schema.json` — the wardrobe format, an `example_wardrobe` (10 items), and an `empty_wardrobe` template.

```python
from utils.data_loader import load_listings, get_example_wardrobe, get_empty_wardrobe
```
