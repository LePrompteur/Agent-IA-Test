"""
Décision du verdict final, indépendante de la déclaration du modèle.

Le statut annoncé par Claude (report_result) n'est qu'une proposition : il est
recoupé avec les assertions enregistrées et les journaux réseau pour éviter les
faux positifs (§5.1 du référentiel : succès affiché alors que l'API a échoué).
"""

from __future__ import annotations

from dataclasses import dataclass, field

VALIDATION_RESOURCE_TYPES = {"xhr", "fetch", "document"}


@dataclass
class Verdict:
    status: str  # PASSED | FAILED | BLOCKED | INCONCLUSIVE | ERROR | SKIPPED
    claimed: str | None
    overrides: list[str] = field(default_factory=list)
    unexpected_http_errors: list[dict] = field(default_factory=list)


def unexpected_errors(http_errors: list[dict], expected_codes: list[int]) -> list[dict]:
    expected = set(expected_codes or [])
    return [
        e for e in http_errors
        if not e.get("mocked")
        and e.get("type") in VALIDATION_RESOURCE_TYPES
        and e.get("status") not in expected
        # Une requête annulée par la navigation n'est pas une panne serveur.
        and not (e.get("status") is None and "ERR_ABORTED" in str(e.get("failure", "")))
    ]


def decide(stop_reason: str, final: dict | None, assertions: list[dict], http_errors: list[dict], expected_codes: list[int]) -> Verdict:
    claimed = final.get("status") if final else None
    unexpected = unexpected_errors(http_errors, expected_codes)

    if stop_reason in ("llm_error", "refusal"):
        return Verdict("ERROR", claimed, [f"Arrêt de la boucle : {stop_reason}."], unexpected)
    if final is None:
        reason = {
            "max_iterations": "Plafond d'itérations atteint sans verdict.",
            "no_progress": "Garde-fou 'actions sans effet' déclenché sans verdict.",
        }.get(stop_reason, f"Aucun verdict transmis (arrêt : {stop_reason}).")
        status = "BLOCKED" if stop_reason in ("max_iterations", "no_progress") else "INCONCLUSIVE"
        return Verdict(status, None, [reason], unexpected)

    status = claimed
    overrides: list[str] = []
    if claimed == "PASSED":
        failed = [a for a in assertions if a["status"] == "FAILED"]
        passed = [a for a in assertions if a["status"] == "PASSED"]
        if failed:
            status = "FAILED"
            overrides.append(f"{len(failed)} assertion(s) en échec malgré un verdict PASSED annoncé.")
        elif not passed:
            status = "INCONCLUSIVE"
            overrides.append("Verdict PASSED annoncé sans aucune assertion PASSED enregistrée.")
        if unexpected:
            status = "FAILED"
            sample = ", ".join(f"{e.get('method')} {e.get('url')} → {e.get('status') or e.get('failure')}" for e in unexpected[:3])
            overrides.append(f"Faux positif évité : erreurs HTTP non attendues pendant le test ({sample}).")
        if stop_reason == "no_progress":
            status = "BLOCKED"
            overrides.append("Garde-fou 'actions sans effet' déclenché : verdict PASSED non recevable.")
    return Verdict(status, claimed, overrides, unexpected)
