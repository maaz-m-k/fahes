"""Istibaq address model: char 3-5-gram logistic regression, then LightGBM over that score
plus address facts. Entry points per the shared contract: ``load()`` and ``AddressModel``."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from istibaq.model.features import FEATURE_NAMES, facts, model_text

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "data" / "model"
N_FEATURES = 2**20


def vectorizer():
    from sklearn.feature_extraction.text import HashingVectorizer

    return HashingVectorizer(analyzer="char", ngram_range=(3, 5), n_features=N_FEATURES,
                             alternate_sign=False, norm="l2", lowercase=True)


class AddressModel:
    """Fraud probability (0 to 1) from the bare address."""

    def __init__(self, directory: Path):
        import lightgbm as lgb

        meta = json.loads((directory / "meta.json").read_text())
        lr = np.load(directory / "lr.npz")
        self.meta = meta
        self.version: str = meta["version"]
        self.cut_date: str = meta["cut_date"]
        self._coef = lr["coef"].astype(np.float32)
        self._intercept = float(lr["intercept"])
        self._suffix_rate: dict[str, float] = meta["suffix_phish_rate"]
        self._default_rate: float = meta["default_suffix_rate"]
        self._booster = lgb.Booster(model_str=(directory / "lgbm.txt").read_text())
        self._vec = vectorizer()

    def lr_scores(self, links: list[str]) -> np.ndarray:
        X = self._vec.transform([model_text(x) for x in links])
        z = X @ self._coef + self._intercept
        return 1.0 / (1.0 + np.exp(-z))

    def matrix(self, links: list[str]) -> np.ndarray:
        lr = self.lr_scores(links)
        rows = [[float(s)] + facts(x, self._suffix_rate, self._default_rate) for x, s in zip(links, lr)]
        return np.asarray(rows, dtype=np.float64)

    def predict_many(self, links: list[str]) -> list[float]:
        if not links:
            return []
        return [float(v) for v in self._booster.predict(self.matrix(list(links)))]

    def predict(self, link: str) -> float:
        return self.predict_many([link])[0]


@lru_cache(maxsize=1)
def _cached(directory: str) -> AddressModel | None:
    d = Path(directory)
    if not (d / "meta.json").exists():
        return None
    return AddressModel(d)


def load(directory: str | Path | None = None) -> AddressModel | None:
    """Return the bundled trained model, or None when no artifact is present."""
    return _cached(str(Path(directory) if directory else ARTIFACT_DIR))


__all__ = ["AddressModel", "FEATURE_NAMES", "load"]
