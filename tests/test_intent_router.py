from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from subgraphs.intent_router import HierarchicalIntentRouter


def _router() -> HierarchicalIntentRouter:
    os.environ["LLM_PROVIDER"] = "none"
    return HierarchicalIntentRouter()


def test_routes_draft_email_hierarchically() -> None:
    route = asyncio.run(
        _router().route(
            "draft a email to harshita.2428cseai25@kiet.edu subject: submit your assignment before 9 may body: submit your database assignment before 9 may 2026"
        )
    )
    assert route.domain == "email"
    assert route.intent == "draft_email"
    assert route.confidence >= 0.8


def test_routes_form_url_to_browser_domain() -> None:
    route = asyncio.run(_router().route("go and fill this form https://forms.gle/4AeEXVwhousHbexu5"))
    assert route.domain == "browser"
    assert route.intent == "browser"
    assert route.start_url == "https://forms.gle/4AeEXVwhousHbexu5"


def test_routes_memory_intents_within_memory_domain() -> None:
    remember = asyncio.run(_router().route("remember project alpha contact"))
    search = asyncio.run(_router().route("search memory project alpha"))

    assert remember.domain == "memory"
    assert remember.intent == "remember"
    assert remember.query == "project alpha contact"

    assert search.domain == "memory"
    assert search.intent == "search_memory"
    assert search.query == "project alpha"
