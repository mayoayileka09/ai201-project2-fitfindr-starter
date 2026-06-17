# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock secondhand-marketplace dataset (`data/listings.json`, loaded via `load_listings()`) and returns the listings that match the user's request. It hard-filters by size and price, then ranks the survivors by how many query keywords overlap their text, so the most relevant item is first.

**Input parameters:**
- `description` (str): Free-text keywords describing the wanted item, e.g. `"vintage graphic tee"`. Lowercased and split into tokens; matched against each listing's `title`, `description`, `style_tags`, and `category`.
- `size` (str | None): Size to filter by, e.g. `"M"`. Case-insensitive **substring** match against the listing's `size` field so `"M"` matches `"S/M"`, `"M/L"`, and `"M"`. `None` skips size filtering.
- `max_price` (float | None): Inclusive price ceiling. A listing passes when `listing["price"] <= max_price`. `None` skips price filtering.

**What it returns:**
A `list[dict]` of full listing dicts, sorted by descending keyword-overlap score (best match first). Each dict carries every original field: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Listings that pass the filters but score `0` keyword overlaps are dropped. Returns `[]` when nothing matches — it never raises.

**What happens if it fails or returns nothing:**
The tool itself returns `[]` rather than raising. The planning loop detects the empty list, writes a helpful message into `session["error"]` (suggesting the user loosen the price, change the size, or use different keywords), and returns early **without** calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the selected listing plus the user's wardrobe and asks the Groq LLM to propose 1–2 complete outfits, naming specific wardrobe pieces to pair with the new item and giving concrete styling moves (tuck, layer, roll cuffs, etc.).

**Input parameters:**
- `new_item` (dict): The listing dict chosen by the loop (`session["selected_item"]`). Its `title`, `category`, `colors`, and `style_tags` are formatted into the prompt.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. May be empty (`{"items": []}`) — must be handled, not assumed non-empty.

**What it returns:**
A non-empty `str` of natural-language styling advice. When the wardrobe has items, the advice references pieces by their `name` (e.g. "your baggy dark-wash jeans"). When the wardrobe is empty, it returns general styling advice for the item (what categories/colors/vibes pair well) instead of failing.

**What happens if it fails or returns nothing:**
Empty wardrobe is a normal branch, not a failure: the tool returns generic styling advice. If the LLM call itself errors (network/API), the tool returns a short fallback string; the loop still stores whatever string came back in `session["outfit_suggestion"]` and continues — a styling miss should not abort an otherwise-good find.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion and the new item into a short, casual, postable caption (Instagram/TikTok OOTD style) — not a product description.

**Input parameters:**
- `outfit` (str): The styling text returned by `suggest_outfit()` (`session["outfit_suggestion"]`).
- `new_item` (dict): The listing dict, used so the caption can name the item, its `price`, and its `platform` once each.

**What it returns:**
A 2–4 sentence `str` suitable as a social caption: casual voice, mentions item name + price + platform naturally, captures the outfit vibe in specific terms. Generated at a higher LLM temperature so different inputs produce visibly different captions.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive error string (e.g. `"Couldn't build a fit card — no outfit suggestion was provided."`) rather than raising. The loop stores that string in `session["fit_card"]`; the UI still shows the listing and outfit panels.

---

### Additional Tools (if any)

None for the core build. (Possible stretch tool: `parse_query(query)` to delegate keyword/size/price extraction to the LLM instead of regex — see State Management.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed, linear pipeline with one early-exit branch. There is no open-ended "pick a tool" reasoning — each step's output is the next step's input, and the only decision point is whether `search_listings` found anything.

1. **Initialize** — `session = _new_session(query, wardrobe)`. All result fields start `None`/`[]`, `error = None`.
2. **Parse the query** — extract `description`, `size`, `max_price` from `query` with regex/string rules and store them in `session["parsed"]`:
   - `max_price`: regex for `under $30` / `$30` / `under 30` → `float`, else `None`.
   - `size`: regex for `size ([A-Z0-9/]+)` or standalone tokens `XS|S|M|L|XL|XXL` / `size 8` → `str`, else `None`.
   - `description`: the query with the matched price/size phrases stripped out → keyword string.
3. **Search** — call `search_listings(description, size, max_price)`; store the list in `session["search_results"]`.
   - **Branch (error path):** `if not session["search_results"]:` set `session["error"] = "No listings matched 'vintage graphic tee' under $30. Try raising your price, removing the size filter, or different keywords."` and **`return session` now.** Do not proceed.
   - **Branch (happy path):** continue.
4. **Select** — `session["selected_item"] = session["search_results"][0]` (top-ranked result).
5. **Suggest outfit** — call `suggest_outfit(session["selected_item"], session["wardrobe"])`; store the string in `session["outfit_suggestion"]`. (Empty wardrobe handled inside the tool — no branch here.)
6. **Fit card** — call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`; store the string in `session["fit_card"]`.
7. **Done** — `return session`. The loop knows it is finished because there are no further steps; success is implied by `session["error"] is None`.

**Termination:** the loop always ends by returning the session — either early at step 3 (with `error` set and downstream fields `None`) or after step 6 (with all three result fields populated and `error is None`). Callers check `session["error"]` first.

---

## State Management

**How does information from one tool get passed to the next?**

All state for a single interaction lives in one `session` dict created by `_new_session()` in `agent.py`. It is the single source of truth — tools are pure functions that take explicit arguments and return values; the loop is the only thing that reads from and writes to the session. Nothing is stored in globals, so each `run_agent()` call is independent.

Fields tracked and how they flow:

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | `_new_session` (from user) | parse step |
| `parsed` (`{description, size, max_price}`) | parse step | `search_listings` args |
| `wardrobe` | `_new_session` (from UI choice) | `suggest_outfit` arg |
| `search_results` (list[dict]) | `search_listings` | empty-check + select step |
| `selected_item` (dict) | select step (`results[0]`) | `suggest_outfit`, `create_fit_card` |
| `outfit_suggestion` (str) | `suggest_outfit` | `create_fit_card`, UI panel 2 |
| `fit_card` (str) | `create_fit_card` | UI panel 3 |
| `error` (str \| None) | error branch | `handle_query` (UI) — checked first |

Flow: `query → parsed → search_results → selected_item → outfit_suggestion → fit_card`. The Gradio `handle_query()` builds the wardrobe from the radio choice, calls `run_agent()`, then maps the returned session to the three panels (or shows `error` in panel 1 with the other two blank).

**Query parsing choice:** regex/string rules (deterministic, no extra API call, easy to test). Documented as a stretch option to swap in an LLM `parse_query` tool if regex proves too brittle.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query (empty list after filtering/scoring) | Set `session["error"]` to a specific, actionable message naming what was searched and offering 3 concrete fixes — e.g. *"No listings matched 'designer ballgown' size XXS under $5. Try raising your max price, dropping the size filter, or using broader keywords like 'formal dress'."* Return the session early; leave `outfit_suggestion` and `fit_card` as `None`; UI shows the message in panel 1, panels 2–3 blank. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Not treated as an error — return general styling advice for the item ("This boxy graphic tee leans 90s grunge: pair it with baggy or wide-leg bottoms and chunky sneakers or boots, and layer an open flannel over it."). The pipeline continues to `create_fit_card`. If the LLM call itself fails, return a brief fallback styling line so the run still completes. |
| create_fit_card | Outfit input is missing or incomplete (empty/whitespace `outfit`) | Return a descriptive string instead of raising — *"Couldn't generate a fit card because no outfit suggestion was available."* The loop stores it in `session["fit_card"]`; the listing and outfit panels still render normally. |

---

## Architecture

```
                          User query (text)  +  wardrobe choice (radio)
                                      │
                                      ▼
                          handle_query()  [app.py]
                            • empty-query guard ──► return ("Enter a query…", "", "")
                            • pick wardrobe: Example vs Empty
                                      │ query, wardrobe
                                      ▼
        ┌──────────────────  run_agent(query, wardrobe)  [agent.py]  ──────────────────┐
        │                                                                              │
        │   _new_session(query, wardrobe) ──► session{query,parsed,search_results,     │
        │                                              selected_item,wardrobe,          │
        │                                              outfit_suggestion,fit_card,error}│
        │        │                                                                     │
        │        ▼                                                                     │
        │   parse query (regex) ──► session["parsed"] = {description, size, max_price} │
        │        │                                                                     │
        │        ▼                                                                     │
        │   ┌─► search_listings(description, size, max_price)  [tools.py]              │
        │   │        │                                                                 │
        │   │        │ results == []                                                   │
        │   │        ├──► session["error"] = "No listings matched…" ──► return session │  ◄── ERROR
        │   │        │                                                                 │      PATH
        │   │        │ results == [item, …]                                            │      returns
        │   │        ▼                                                                 │      here
        │   │   session["search_results"] = results                                    │
        │   │   session["selected_item"]  = results[0]                                 │
        │   │        │ selected_item, wardrobe                                         │
        │   ├─► suggest_outfit(selected_item, wardrobe)  [tools.py → Groq LLM]         │
        │   │        │  (empty wardrobe → general advice)                              │
        │   │        ▼                                                                 │
        │   │   session["outfit_suggestion"] = "…"                                     │
        │   │        │ outfit_suggestion, selected_item                                │
        │   └─► create_fit_card(outfit_suggestion, selected_item)  [tools.py → Groq]   │
        │            │  (empty outfit → descriptive error string)                      │
        │            ▼                                                                 │
        │        session["fit_card"] = "…"                                             │
        │            │                                                                 │
        └────────────┼─────────────────────────────────────────────────────────────────┘
                     ▼
              return session
                     │
                     ▼
        handle_query() maps session ──►  ┌ panel 1: 🛍️ listing (or error)
                                         ├ panel 2: 👗 outfit_suggestion
                                         └ panel 3: ✨ fit_card
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **`search_listings`** — I'll give Claude the **Tool 1** block above (all four fields) plus the `search_listings` docstring and `load_listings()` from `utils/data_loader.py`. I expect a function that: loads listings, filters by `max_price` (inclusive) and case-insensitive substring `size`, scores remaining listings by keyword overlap across `title`/`description`/`style_tags`/`category`, drops score-0 items, and returns the dicts sorted by score. **Verify before trusting:** read the code to confirm all three params are applied and `[]` is returned (not an exception) when nothing matches; then run 3 queries — `"vintage graphic tee", max_price=30` (expect `lst_006`/`lst_033` near top, no items > $30), `"track jacket", size="M"` (expect `lst_004`), and the no-match `"designer ballgown", size="XXS", max_price=5` (expect `[]`).
- **`suggest_outfit`** — I'll give Claude the **Tool 2** block, the `wardrobe_schema.json` shape, and the empty-wardrobe requirement. Expect a function that branches on `wardrobe["items"]` being empty, builds a prompt naming wardrobe pieces, and calls Groq via `_get_groq_client()`. **Verify:** run once with `get_example_wardrobe()` (output must name real items like the baggy jeans / chunky sneakers) and once with `get_empty_wardrobe()` (must still return non-empty general advice, not crash).
- **`create_fit_card`** — I'll give Claude the **Tool 3** block and the style guidelines from the docstring. Expect a guard on empty `outfit`, a higher-temperature Groq call, and a 2–4 sentence caption mentioning item/price/platform once each. **Verify:** call with a real outfit string (caption is casual + names price/platform), and with `""` (returns the descriptive error string, no exception).

**Milestone 4 — Planning loop and state management:**

- **`run_agent` / planning loop** — I'll give Claude the **Planning Loop**, **State Management**, and **Architecture** (diagram) sections, plus the `_new_session()` and `run_agent()` stubs in `agent.py`. Expect the exact 7-step pipeline with the early-return branch when `search_results` is empty, writing each result to the matching session field. **Verify:** run the CLI block in `agent.py` — happy path populates `selected_item`/`outfit_suggestion`/`fit_card` with `error is None`; no-results path sets `error` and leaves the other fields `None`. Confirm `suggest_outfit` is never called on empty results.
- **`handle_query` (Gradio)** — I'll give Claude the `handle_query` TODO and the State Management table. Expect: empty-query guard, wardrobe selection from the radio value, `run_agent()` call, `error`→panel-1 mapping, and a formatted listing string. **Verify:** launch `app.py`, run an example query and the deliberate no-results query, confirm all three panels behave per the table.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr needs to do:** FitFindr is a thrift-shopping agent that turns a natural-language request into a concrete find-and-style recommendation. A user's request triggers `search_listings` to filter the mock marketplace by description, size, and price; the top result then triggers `suggest_outfit`, which pairs it against the user's wardrobe, and that styling suggestion triggers `create_fit_card` to produce a short, postable caption. If `search_listings` returns nothing, the agent sets an error message telling the user what to adjust and stops without calling the downstream tools; if the wardrobe is empty, `suggest_outfit` falls back to generic styling advice, and if the outfit text is missing, `create_fit_card` returns a descriptive error instead of crashing.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse + Search:** The loop parses the query into `parsed = {description: "vintage graphic tee", size: None, max_price: 30.0}`, then calls `search_listings(description="vintage graphic tee", size=None, max_price=30.0)`. Price filtering excludes items over $30; keyword scoring ranks the matches, returning e.g. `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24, depop, good), `lst_033` ("Vintage Band Tee — Faded Grey", $19), `lst_015` ("Vintage Graphic Hoodie", $26). `session["search_results"]` is non-empty, so the loop sets `session["selected_item"] = lst_006`.

**Step 2 — Suggest outfit:** The loop calls `suggest_outfit(new_item=<lst_006>, wardrobe=<example wardrobe>)`. Using the wardrobe's baggy dark-wash jeans (`w_001`) and chunky white sneakers (`w_007`), it returns and stores in `session["outfit_suggestion"]`: *"Tuck the front of this boxy graphic tee into your baggy dark-wash jeans and finish with the chunky white sneakers — throw the vintage black denim jacket over the top for a layered 90s streetwear look."*

**Step 3 — Fit card:** The loop calls `create_fit_card(outfit=<suggestion>, new_item=<lst_006>)`, storing in `session["fit_card"]`: *"scored this bootleg graphic tee off depop for $24 🫶 styled it with my baggy jeans + chunky sneakers and a denim jacket — full fit's in my stories."*

**Final output to user:** `handle_query()` maps the returned session to the three panels — panel 1 shows the formatted listing (title, $24, depop, good condition), panel 2 shows the wardrobe-specific outfit idea, panel 3 shows the fit-card caption. `session["error"]` is `None`, so no error is displayed.

**Contrast — no-results path (`"designer ballgown size XXS under $5"`):** `search_listings` filters everything out and returns `[]`. The loop sets `session["error"] = "No listings matched 'designer ballgown' size XXS under $5. Try raising your max price, dropping the size filter, or using broader keywords."` and returns immediately. `suggest_outfit` and `create_fit_card` are never called; the UI shows the error in panel 1 and leaves panels 2–3 blank.
