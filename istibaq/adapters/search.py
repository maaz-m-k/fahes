"""Search adapters: Brave Search API and Google Places, plus the shared :class:`SearchResult`.

Both return a flat list of :class:`SearchResult` labelled ``live`` (first-party APIs).
Google results and sponsored ads come from DataForSEO (``dataforseo.py``), labelled
``borrowed`` and used only by the on-demand Google and ads check.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx

from .base import CostSink, check, env_key, make_client, no_cost

# Published list prices (USD per request), used for the cost log.
BRAVE_COST = 0.005
PLACES_COST = 0.035  # Text Search with websiteUri (Enterprise field tier)


@dataclass
class SearchResult:
    source: str        # "brave", "places", "google", "google_ad", "google_ai"
    kind: str          # "organic", "ad", "ai_cited", "maps"
    query: str
    position: int
    title: str
    link: str
    snippet: str
    label: str         # "borrowed" or "live"
    phone: str = ""    # Maps listings: the listing's phone number, judged against the register

    def to_dict(self) -> dict:
        return asdict(self)


class BraveSearch:
    """Brave Search API web results."""

    name = "brave"
    url = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, client: httpx.Client | None = None, cost_sink: CostSink = no_cost):
        self.client = make_client(client)
        self.cost_sink = cost_sink

    def search(self, query: str, lang: str = "en") -> list[SearchResult]:
        params = {"q": query, "country": "AE", "search_lang": lang, "count": 10}
        headers = {"X-Subscription-Token": env_key("BRAVE_API_KEY"), "Accept": "application/json"}
        resp = check(self.client.get(self.url, params=params, headers=headers), self.name)
        self.cost_sink(self.name, BRAVE_COST, {"query": query})
        results = ((resp.json().get("web") or {}).get("results")) or []
        return [SearchResult(self.name, "organic", query, i, r.get("title", ""), r.get("url", ""),
                             r.get("description", ""), "live")
                for i, r in enumerate(results, 1) if r.get("url")]


class PlacesSearch:
    """Google Places API (New) Text Search: Maps listings and their websites."""

    name = "places"
    url = "https://places.googleapis.com/v1/places:searchText"
    field_mask = "places.displayName,places.websiteUri,places.formattedAddress,places.nationalPhoneNumber"

    def __init__(self, client: httpx.Client | None = None, cost_sink: CostSink = no_cost):
        self.client = make_client(client)
        self.cost_sink = cost_sink

    def search(self, query: str, lang: str = "en") -> list[SearchResult]:
        body = {"textQuery": query, "languageCode": lang, "regionCode": "AE"}
        headers = {"X-Goog-Api-Key": env_key("GOOGLE_PLACES_API_KEY"), "X-Goog-FieldMask": self.field_mask}
        resp = check(self.client.post(self.url, json=body, headers=headers), self.name)
        self.cost_sink(self.name, PLACES_COST, {"query": query})
        out = []
        for i, p in enumerate(resp.json().get("places") or [], 1):
            site = p.get("websiteUri") or ""
            phone = p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or ""
            if not site and not phone:
                continue  # nothing to judge
            title = (p.get("displayName") or {}).get("text", "")
            snippet = " · ".join(x for x in (p.get("formattedAddress"), phone) if x)
            out.append(SearchResult(self.name, "maps", query, i, title, site, snippet, "live", phone))
        return out
