import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT / "src"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Environnements où Playwright ne trouve pas son navigateur par défaut (ex. Chromium pré-installé).
_PREINSTALLED = Path("/opt/pw-browsers/chromium")
if "PLAYWRIGHT_CHROMIUM_EXECUTABLE" not in os.environ and _PREINSTALLED.exists():
    os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = str(_PREINSTALLED)

from agent.config import load_config  # noqa: E402
from agent.llm import Usage  # noqa: E402
from tests.fixtures.app.server import start_fixture_server  # noqa: E402


@pytest.fixture(scope="session")
def fixture_url():
    server = start_fixture_server()
    os.environ["FIXTURE_BASE_URL"] = server.base_url
    yield server.base_url
    server.stop()
    os.environ.pop("FIXTURE_BASE_URL", None)


@pytest.fixture
def config():
    cfg = load_config()
    cfg["settle_ms"] = 150
    return cfg


class FakeLLM:
    """Modèle scripté : chaque tour renvoie la liste d'appels d'outils fournie.

    Un élément du script peut être une liste de (nom, paramètres), ou une
    fonction (messages) -> liste de (nom, paramètres). Liste vide = fin de tour.
    """

    def __init__(self, script, repeat_last=False):
        self.script = list(script)
        self.repeat_last = repeat_last
        self.calls = 0
        self.usage = Usage()
        self.received = []

    def create(self, system, messages, tools):
        self.calls += 1
        self.received.append(messages[-1])
        if self.script:
            step = self.script.pop(0) if (len(self.script) > 1 or not self.repeat_last) else self.script[0]
        else:
            step = []
        if callable(step):
            step = step(messages)
        blocks = [SimpleNamespace(type="tool_use", id=f"tu_{self.calls}_{i}", name=name, input=inp) for i, (name, inp) in enumerate(step)]
        if not blocks:
            blocks = [SimpleNamespace(type="text", text="Terminé.")]
        return SimpleNamespace(content=blocks, stop_reason="tool_use" if step else "end_turn",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def fake_llm():
    return FakeLLM
