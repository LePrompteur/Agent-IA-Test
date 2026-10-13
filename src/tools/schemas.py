"""
Définition des schémas d'outils au format Claude Tool Use API.

Source unique : tool_schemas.json (groupes "browser", "code", "diagnosis").
"""

import json
from pathlib import Path

_SCHEMAS = json.loads((Path(__file__).parent / "tool_schemas.json").read_text(encoding="utf-8"))

BROWSER_TOOLS = _SCHEMAS["browser"]
CODE_TOOLS = _SCHEMAS["code"]
DIAGNOSIS_TOOLS = _SCHEMAS["diagnosis"]

# Outils qui modifient l'état de la page : surveillés par le garde-fou "action sans effet".
MUTATING_TOOLS = {
    "click_element", "fill_input", "select_option", "upload_file",
    "press_key", "browser_navigation",
}

# Compatibilité avec le squelette initial.
TOOLS = BROWSER_TOOLS


def tools_for(*groups: str) -> list[dict]:
    tools: list[dict] = []
    for group in groups:
        tools.extend(_SCHEMAS[group])
    return tools
