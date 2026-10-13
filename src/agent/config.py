"""Chargement de la configuration et des scénarios (avec substitution ${VAR:-défaut})."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")
SECRET_HINTS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY")


def load_config(path: Path | None = None) -> dict:
    path = path or PROJECT_ROOT / "config" / "config.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scenario_variables(scenario: Any) -> set[str]:
    text = json.dumps(scenario)
    return {m.group(1) for m in VAR_PATTERN.finditer(text)}


def substitute(value: Any, missing: set[str], secrets: set[str]) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            name, default = m.group(1), m.group(2)
            resolved = os.environ.get(name, default)
            if resolved is None:
                missing.add(name)
                return m.group(0)
            if any(h in name for h in SECRET_HINTS) and resolved:
                secrets.add(resolved)
            return resolved
        return VAR_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [substitute(v, missing, secrets) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, missing, secrets) for k, v in value.items()}
    return value


def load_scenario(path: Path) -> tuple[dict, set[str], set[str]]:
    """Renvoie (scénario résolu, variables manquantes, valeurs secrètes à masquer)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    missing: set[str] = set()
    secrets: set[str] = set()
    resolved = substitute(raw, missing, secrets)
    resolved.setdefault("expected_http_errors", [])
    resolved.setdefault("success_criteria", [])
    resolved.setdefault("steps", [])
    return resolved, missing, secrets


def redact(text: Any, secrets: set[str]) -> Any:
    if isinstance(text, str):
        for s in secrets:
            text = text.replace(s, "***")
        return text
    if isinstance(text, list):
        return [redact(t, secrets) for t in text]
    if isinstance(text, dict):
        return {k: redact(v, secrets) for k, v in text.items()}
    return text
