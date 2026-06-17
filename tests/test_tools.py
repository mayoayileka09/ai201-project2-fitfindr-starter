"""
Tests for the three FitFindr tools.

Run from the project root with:
    pytest tests/

The search_listings tests are fully deterministic (no network). The two
LLM-backed tools (suggest_outfit, create_fit_card) make live Groq calls and
require GROQ_API_KEY in .env — they are skipped automatically when no key
is present, so the deterministic suite still runs in any environment.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

# Tools call load_dotenv() on import, so GROQ_API_KEY is already loaded here.
needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM tests",
)


# ── search_listings (deterministic) ─────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # Every result is a full listing dict with the expected fields.
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, never an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_is_substring_and_case_insensitive():
    # "m" should match listings sized "M" and "M/L".
    results = search_listings("jacket", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    # More keyword overlap should rank a listing ahead of a weaker match.
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    # The very loosely related belt/shoes shouldn't outrank a graphic tee.
    titles = [item["title"] for item in results]
    assert any("Tee" in t or "tee" in t.lower() for t in titles[:3])


# ── suggest_outfit (live LLM) ───────────────────────────────────────────────

@needs_groq
def test_suggest_outfit_with_wardrobe_returns_text():
    item = search_listings("vintage graphic tee", size=None, max_price=30)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip()


@needs_groq
def test_suggest_outfit_empty_wardrobe_does_not_crash():
    # Failure mode: empty wardrobe → still returns non-empty general advice.
    item = search_listings("vintage graphic tee", size=None, max_price=30)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip()


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_message():
    # Failure mode: missing/empty outfit → descriptive string, no exception.
    # No API call is made because the guard returns before the LLM call.
    item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    result = create_fit_card("   ", item)
    assert isinstance(result, str)
    assert "fit card" in result.lower()


@needs_groq
def test_create_fit_card_returns_caption():
    item = search_listings("vintage graphic tee", size=None, max_price=30)[0]
    outfit = "Pair it with baggy jeans and chunky white sneakers."
    result = create_fit_card(outfit, item)
    assert isinstance(result, str)
    assert result.strip()
