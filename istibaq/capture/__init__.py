"""Two-view capture (server and phone) of suspect pages."""
from .twoview import Capture, CaptureRefused, Hop, Shot, View, capture, compare, detect_brand, detect_wall

__all__ = ["Capture", "CaptureRefused", "Hop", "Shot", "View", "capture", "compare", "detect_brand", "detect_wall"]
