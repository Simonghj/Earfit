"""Live web sourcing via the Tavily Search API: where to buy the chosen silicone and get the mold printed."""

from __future__ import annotations

import json
import os
import urllib.request

TAVILY_URL = "https://api.tavily.com/search"


def _search(key: str, query: str) -> list[dict]:
    request = urllib.request.Request(
        TAVILY_URL,
        data=json.dumps({"query": query, "max_results": 3, "search_depth": "basic"}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response).get("results", [])


def find_supplies(silicone: str) -> list[dict]:
    """Search the web for the design's silicone and a 3D-print service; returns [{topic, title, url, snippet}]."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    queries = {
        "silicone": f"buy {silicone} skin-safe platinum silicone small trial kit",
        "printing": "online 3D printing service upload STL file",
    }
    return [
        {
            "topic": topic,
            "title": hit.get("title", ""),
            "url": hit.get("url", ""),
            "snippet": (hit.get("content") or "")[:180],
        }
        for topic, query in queries.items()
        for hit in _search(key, query)
    ]
