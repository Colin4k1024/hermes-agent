import pytest


@pytest.fixture(autouse=True)
def state_service_local_debug(monkeypatch):
    """State service tests run in local mode unless a test overrides it."""
    monkeypatch.setenv("STATE_DEBUG", "true")

