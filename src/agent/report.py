"""Rapports JSON + Markdown dans ./reports/."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from agent.config import PROJECT_ROOT


def new_run_dir(label: str, base: Path | None = None) -> Path:
    base = base or PROJECT_ROOT / "reports"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / f"{stamp}_{re.sub(r'[^A-Za-z0-9_-]', '_', label)[:60]}"
    suffix = 1
    while path.exists():
        suffix += 1
        path = path.with_name(f"{path.name}-{suffix}")
    path.mkdir(parents=True)
    return path


def _cell(text: object, limit: int = 120) -> str:
    s = str(text).replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= limit else s[:limit] + "…"


def write_report(run_dir: Path, report: dict) -> tuple[Path, Path]:
    json_path = run_dir / "report.json"
    md_path = run_dir / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(r: dict) -> str:
    v = r.get("verdict", {})
    lines = [f"# {r.get('title', 'Rapport')}", ""]
    lines += [
        f"- **Verdict final : {v.get('status')}**" + (f" (annoncé par l'agent : {v.get('claimed')})" if v.get("claimed") and v.get("claimed") != v.get("status") else ""),
        f"- Mode : {r.get('mode')}",
        f"- Arrêt de la boucle : {r.get('stop_reason')} après {r.get('iterations')} tour(s)",
        f"- Durée : {r.get('duration_s')} s",
    ]
    if r.get("expected_verdict"):
        lines.append(f"- Verdict attendu (eval) : {' / '.join(r['expected_verdict'])} → {'conforme' if r.get('eval_conform') else 'NON CONFORME'}")
    if r.get("error"):
        lines.append(f"- Erreur : {r['error']}")
    for o in v.get("overrides", []):
        lines.append(f"- ⚠ Requalification : {o}")
    lines.append("")

    if r.get("objective"):
        lines += ["## Objectif", r["objective"], ""]

    final = r.get("final") or {}
    if final:
        lines += ["## Synthèse de l'agent", final.get("summary", ""), ""]
        if final.get("root_cause"):
            lines += ["## Cause racine", final["root_cause"], ""]
            if final.get("suspected_component"):
                lines.append(f"Composant suspecté : `{final['suspected_component']}`\n")
            if final.get("confidence"):
                lines.append(f"Confiance : {final['confidence']}\n")
        for title, key in (("Preuves", "evidence"), ("Recommandations", "recommendations")):
            if final.get(key):
                lines += [f"### {title}"] + [f"- {e}" for e in final[key]] + [""]

    if r.get("assertions"):
        lines += ["## Assertions", "| Statut | Attendu | Justification |", "|---|---|---|"]
        lines += [f"| {a['status']} | {_cell(a['expectation'])} | {_cell(a['reason'], 200)} |" for a in r["assertions"]]
        lines.append("")

    if r.get("actions"):
        lines += ["## Actions", "| # | Tour | Outil | Paramètres | OK | Résultat |", "|---|---|---|---|---|---|"]
        for a in r["actions"]:
            lines.append(f"| {a['n']} | {a['iteration']} | {a['tool']} | {_cell(json.dumps(a['input'], ensure_ascii=False), 80)} | {'✓' if a['ok'] else '✗'} | {_cell(a['result'])} |")
        lines.append("")

    diag = r.get("diagnostics", {})
    if diag.get("http_errors"):
        lines += ["## Erreurs HTTP", "| Méthode | URL | Statut | Type | Simulée |", "|---|---|---|---|---|"]
        for e in diag["http_errors"][:30]:
            lines.append(f"| {e.get('method')} | {_cell(e.get('url'), 90)} | {e.get('status') or e.get('failure')} | {e.get('type')} | {'oui' if e.get('mocked') else ''} |")
        lines.append("")
    if diag.get("console"):
        lines += ["## Console JavaScript"] + [f"- `{c['level']}` {_cell(c['text'], 200)}" for c in diag["console"][:30]] + [""]

    if r.get("fixes"):
        lines.append("## Correctifs")
        for f in r["fixes"]:
            lines += [f"### `{f['path']}` — {'appliqué' if f['applied'] else 'proposé'}", f["rationale"], "", "```diff", f["diff"].rstrip(), "```", ""]

    if r.get("screenshots"):
        lines += ["## Captures d'écran"] + [f"- `{Path(s).name}`" for s in r["screenshots"]] + [""]

    if r.get("usage"):
        u = r["usage"]
        lines += ["## Consommation", f"{u['calls']} appels · {u['input_tokens']} jetons en entrée · {u['output_tokens']} en sortie · {u['cache_read_input_tokens']} lus en cache", ""]
    return "\n".join(lines)


def write_summary(run_dir: Path, results: list[dict]) -> Path:
    (run_dir / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["# Synthèse de campagne", "", " · ".join(f"**{k}** : {n}" for k, n in sorted(counts.items())), "",
             "| Scénario | Priorité | Verdict | Attendu | Conforme | Rapport |", "|---|---|---|---|---|---|"]
    for r in results:
        expected = " / ".join(r.get("expected_verdict") or [])
        conform = "" if not expected else ("✓" if r.get("eval_conform") else "✗")
        lines.append(f"| {r['id']} {_cell(r['name'], 60)} | {r.get('priority', '')} | {r['status']} | {expected} | {conform} | {r.get('report', '')} |")
    path = run_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
