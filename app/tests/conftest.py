import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(autouse=True)
def no_live_gemini(monkeypatch):
    """Tests never reach Google with a key from app/.env. A test that needs a key sets its own."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
