"""External-service adapters. Each has a recorded fake in tests/fixtures/recorded/."""
from .base import AdapterError, CostSink, MissingKey, no_cost
from .ct import CTReader
from .nrd import NewDomains
from .openrouter import AILayer
from .rdap import RDAP
from .dataforseo import GoogleSearch
from .search import BraveSearch, PlacesSearch, SearchResult

__all__ = ["AdapterError", "AILayer", "BraveSearch", "CostSink", "CTReader", "GoogleSearch", "MissingKey", "NewDomains",
           "PlacesSearch", "RDAP", "SearchResult", "no_cost"]
