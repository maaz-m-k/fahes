import pytest


@pytest.fixture(autouse=True)
def _no_paid_google(monkeypatch):
    """DataForSEO is switched off with no credentials unless a test turns it on against a fake."""
    for k in ("ISTIBAQ_DATAFORSEO", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests run offline: any socket connection attempt fails loudly."""
    import socket

    def guard(*args, **kwargs):
        raise RuntimeError("network access is not allowed in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
