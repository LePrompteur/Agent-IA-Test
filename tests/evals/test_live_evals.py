"""
Evals de bout en bout avec le vrai modèle (consomment des jetons).

Lancement : ANTHROPIC_API_KEY=... pytest tests/evals/test_live_evals.py -m live
Ignorées automatiquement sans identifiants.
"""

import json
import os
from pathlib import Path

import pytest

from agent.runner import Runner

ROOT = Path(__file__).resolve().parents[2]
EVAL_SCENARIOS = sorted(
    f for f in (ROOT / "scenarios").glob("*.json")
    if json.loads(f.read_text()).get("expected_verdict")
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
                       reason="ANTHROPIC_API_KEY non défini"),
]


@pytest.mark.parametrize("scenario", EVAL_SCENARIOS, ids=lambda p: p.stem)
def test_agent_meets_expected_verdict(scenario, config, tmp_path, fixture_url):
    result = Runner(config, log=lambda *_: None).run_scenario(scenario, run_base=tmp_path)
    assert result["eval_conform"], f"Verdict {result['status']} ≠ attendu {result['expected_verdict']} — voir {result['report']}"
