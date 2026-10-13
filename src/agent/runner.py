"""Exécution d'un scénario de test, d'une campagne complète, et du mode débug."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from agent.config import PROJECT_ROOT, load_scenario, redact
from agent.llm import ClaudeClient, LLMError
from agent.loop import AgentLoop, ToolExecutor
from agent.report import new_run_dir, write_report, write_summary
from agent.verdict import Verdict, decide
from tools.browser import BrowserLaunchError, BrowserSession
from tools.code_tools import CodeWorkspace
from tools.schemas import tools_for

PROMPTS_DIR = PROJECT_ROOT / "src" / "prompts"


def read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def scenario_brief(s: dict) -> str:
    parts = [
        f"# Scénario {s.get('id')} — {s.get('name')}",
        f"Catégorie : {s.get('category', 'n/c')} · Priorité : {s.get('priority', 'n/c')}",
        f"URL cible : {s.get('target_url')}",
        f"Objectif : {s.get('objective')}",
    ]
    if s.get("viewport"):
        parts.append(f"Viewport imposé au démarrage : {s['viewport']['width']}x{s['viewport']['height']}")
    if s.get("steps"):
        parts.append("Étapes indicatives :\n" + "\n".join(f"{i}. {st}" for i, st in enumerate(s["steps"], 1)))
    if s.get("success_criteria"):
        parts.append("Critères de succès (tous requis pour PASSED) :\n" + "\n".join(f"- {c}" for c in s["success_criteria"]))
    if s.get("expected_http_errors"):
        parts.append(f"Codes HTTP d'erreur attendus dans ce scénario (ne pas les considérer comme des pannes) : {s['expected_http_errors']}")
    if s.get("test_data"):
        parts.append("Données de test :\n" + json.dumps(s["test_data"], ensure_ascii=False, indent=1))
    if s.get("notes"):
        parts.append(f"Notes : {s['notes']}")
    parts.append("Commencez par naviguer vers l'URL cible. Terminez obligatoirement par report_result.")
    return "\n\n".join(parts)


class Runner:
    def __init__(self, config: dict, source_dir: Path | None = None, apply_fixes: bool = False,
                 log: Callable[[str], None] = print, llm_factory: Callable[[dict], object] | None = None):
        self.config = config
        self.source_dir = source_dir
        self.apply_fixes = apply_fixes
        self.log = log
        self.llm_factory = llm_factory or (lambda cfg: ClaudeClient(cfg))
        self._fixture = None

    # ------------------------------------------------------------------ banc d'essai
    def ensure_fixture(self, scenario_path: Path) -> None:
        """Démarre l'application de démonstration si le scénario y fait référence."""
        if "FIXTURE_BASE_URL" in os.environ or self._fixture:
            return
        if "${FIXTURE_BASE_URL" not in scenario_path.read_text(encoding="utf-8"):
            return
        from tests.fixtures.app.server import start_fixture_server
        self._fixture = start_fixture_server()
        os.environ["FIXTURE_BASE_URL"] = self._fixture.base_url
        self.log(f"🧪 Application de démonstration démarrée sur {self._fixture.base_url}")

    def shutdown(self) -> None:
        if self._fixture:
            self._fixture.stop()
            os.environ.pop("FIXTURE_BASE_URL", None)
            self._fixture = None

    # ------------------------------------------------------------------ scénario
    def run_scenario(self, scenario_path: Path, run_base: Path | None = None) -> dict:
        self.ensure_fixture(scenario_path)
        scenario, missing, secrets = load_scenario(scenario_path)
        sid = scenario.get("id", scenario_path.stem)
        self.log(f"\n🔄 {sid} — {scenario.get('name')}")
        run_dir = new_run_dir(sid, run_base)
        base = {"id": sid, "name": scenario.get("name"), "priority": scenario.get("priority"),
                "expected_verdict": scenario.get("expected_verdict")}

        if missing:
            reason = f"Variables d'environnement manquantes : {sorted(missing)}"
            self.log(f"⏭  SKIPPED — {reason}")
            report = {"title": f"{sid} — {scenario.get('name')}", "mode": "scenario", "verdict": {"status": "SKIPPED", "claimed": None, "overrides": []},
                      "stop_reason": "skipped", "iterations": 0, "duration_s": 0, "error": reason, "objective": scenario.get("objective")}
            write_report(run_dir, report)
            return {**base, "status": "SKIPPED", "report": str(run_dir / "report.md")}

        cfg = dict(self.config)
        if scenario.get("viewport"):
            cfg["viewport"] = scenario["viewport"]
        t0 = time.monotonic()
        browser = BrowserSession(cfg, run_dir)
        tools = tools_for("browser")
        llm = self.llm_factory(cfg)
        executor = ToolExecutor(tools, browser=browser, no_change_limit=int(cfg.get("no_change_limit", 3)),
                                secrets=secrets, screenshot_on_failure=cfg.get("screenshot_on_failure", True), log=self.log)
        try:
            browser.start()
            loop = AgentLoop(llm, executor, tools, int(cfg.get("max_iterations", 15)), log=self.log)
            result = loop.run(read_prompt("system_prompt.txt"), scenario_brief(scenario))
            verdict = decide(result.stop_reason, executor.final, executor.assertions,
                             browser.http_errors(), scenario.get("expected_http_errors", []))
            if verdict.status != "PASSED":
                browser.screenshot("final_state")
            diagnostics = {"http_errors": browser.http_errors(), "console": browser.console}
            screenshots = list(browser.screenshots)
        finally:
            browser.close()

        report = self._build_report(scenario, sid, verdict, result, executor, diagnostics, screenshots, llm, t0)
        if verdict.status in ("FAILED", "BLOCKED") and self.source_dir:
            self.log("🔧 Échec détecté : analyse du code source et proposition de correctif…")
            fix_report = self.debug_from_failure(report, run_dir)
            report["fix_session"] = {k: fix_report.get(k) for k in ("verdict", "final", "stop_reason", "error")}
            report["fixes"] = fix_report.get("fixes", [])
        json_path, md_path = write_report(run_dir, redact(report, secrets))
        self._print_verdict(report, md_path)
        return {**base, "status": verdict.status, "eval_conform": report.get("eval_conform"), "report": str(md_path)}

    def _build_report(self, scenario, sid, verdict: Verdict, result, executor, diagnostics, screenshots, llm, t0) -> dict:
        expected = scenario.get("expected_verdict")
        report = {
            "title": f"{sid} — {scenario.get('name')}",
            "mode": "scenario",
            "scenario": scenario,
            "objective": scenario.get("objective"),
            "verdict": verdict.__dict__,
            "expected_verdict": expected,
            "stop_reason": result.stop_reason,
            "iterations": result.iterations,
            "error": result.error,
            "final": executor.final,
            "final_text": result.final_text,
            "assertions": executor.assertions,
            "actions": executor.actions,
            "diagnostics": diagnostics,
            "screenshots": screenshots,
            "usage": getattr(llm, "usage", None).as_dict() if getattr(llm, "usage", None) else None,
            "duration_s": round(time.monotonic() - t0, 1),
        }
        if expected:
            ok = verdict.status in expected
            if scenario.get("expected_stop_reason"):
                ok = ok and result.stop_reason in scenario["expected_stop_reason"]
            report["eval_conform"] = ok
        return report

    def _print_verdict(self, report: dict, md_path: Path) -> None:
        v = report["verdict"]
        icon = {"PASSED": "✅", "FAILED": "❌", "BLOCKED": "⛔"}.get(v["status"], "⚠️")
        self.log(f"{icon} Verdict : {v['status']}" + (f" (annoncé : {v['claimed']})" if v["claimed"] and v["claimed"] != v["status"] else ""))
        for o in v["overrides"]:
            self.log(f"   ⚠ {o}")
        final = report.get("final") or {}
        if final.get("root_cause"):
            self.log(f"🔎 Cause racine : {final['root_cause']}")
        if "eval_conform" in report:
            self.log(f"🎯 Eval : {'conforme' if report['eval_conform'] else 'NON CONFORME'} (attendu {report['expected_verdict']})")
        self.log(f"📄 Rapport : {md_path}")

    # ------------------------------------------------------------------ campagne
    def run_all(self, scenarios_dir: Path, only: str | None = None) -> list[dict]:
        files = sorted(scenarios_dir.glob("*.json"))
        if only:
            files = [f for f in files if only in f.stem]
        campaign_dir = new_run_dir("run-all")
        results = []
        try:
            for f in files:
                try:
                    results.append(self.run_scenario(f, run_base=campaign_dir))
                except (BrowserLaunchError, LLMError) as exc:
                    if isinstance(exc, LLMError) and not exc.fatal:
                        raise
                    self.log(f"⛔ Campagne interrompue : {exc}")
                    results.append({"id": f.stem, "name": f.stem, "status": "ERROR", "report": str(exc)})
                    break
                except Exception as exc:  # une panne isolée ne doit pas arrêter la campagne
                    self.log(f"💥 {f.name} : {exc}")
                    results.append({"id": f.stem, "name": f.stem, "status": "ERROR", "report": str(exc)})
        finally:
            self.shutdown()
        summary = write_summary(campaign_dir, results)
        self.log(f"\n📊 Synthèse : {summary}")
        return results

    # ------------------------------------------------------------------ débug & correction
    def debug_target(self, target: str) -> dict:
        is_url = target.startswith(("http://", "https://"))
        if not is_url:
            path = Path(target).resolve()
            if not path.exists():
                raise FileNotFoundError(f"Cible introuvable : {target}")
            source_dir = self.source_dir or (Path.cwd() if Path.cwd() in path.parents else path.parent)
            rel = path.relative_to(source_dir.resolve()).as_posix()
            brief = (f"Mode débug sur le fichier source `{rel}` (dossier source : {source_dir}).\n"
                     "Analysez ce fichier et ses dépendances directes, identifiez les défauts (bugs, erreurs de logique, "
                     "gestion d'erreurs absente, failles évidentes), établissez la cause racine du plus grave et proposez un correctif avec propose_fix.")
            return self._debug_session(brief, label=f"debug_{path.name}", source_dir=source_dir, with_browser=False)
        brief = (f"Mode débug sur l'URL {target}.\n"
                 "Chargez la page, explorez les interactions principales, collectez les erreurs console et réseau, "
                 "reproduisez le dysfonctionnement le plus significatif et établissez sa cause racine."
                 + (" Localisez ensuite le code responsable dans le dossier source et proposez un correctif avec propose_fix." if self.source_dir else
                    " Aucun dossier source n'est fourni : limitez-vous au diagnostic côté client et serveur observable."))
        return self._debug_session(brief, label="debug_url", source_dir=self.source_dir, with_browser=True)

    def debug_from_failure(self, failed_report: dict, run_dir: Path) -> dict:
        context = {
            "scenario": failed_report.get("scenario"),
            "verdict": failed_report.get("verdict"),
            "agent_conclusion": failed_report.get("final"),
            "failed_assertions": [a for a in failed_report.get("assertions", []) if a["status"] == "FAILED"],
            "last_actions": failed_report.get("actions", [])[-8:],
            "http_errors": failed_report.get("diagnostics", {}).get("http_errors", [])[:20],
            "console": failed_report.get("diagnostics", {}).get("console", [])[:20],
        }
        brief = ("Un test E2E vient d'échouer. Voici le contexte d'exécution :\n```json\n"
                 + json.dumps(context, ensure_ascii=False, indent=1, default=str)
                 + "\n```\nLocalisez dans le dossier source le code responsable, établissez la cause racine et proposez un correctif avec propose_fix.")
        return self._debug_session(brief, label="fix", source_dir=self.source_dir, with_browser=False, run_dir=run_dir / "fix")

    def _debug_session(self, brief: str, label: str, source_dir: Path | None, with_browser: bool, run_dir: Path | None = None) -> dict:
        run_dir = run_dir or new_run_dir(label)
        run_dir.mkdir(parents=True, exist_ok=True)
        groups = (["browser"] if with_browser else []) + (["code"] if source_dir else []) + ["diagnosis"]
        tools = [t for t in tools_for(*groups) if t["name"] != "report_result"]
        workspace = CodeWorkspace(source_dir, self.apply_fixes, run_dir / "backups") if source_dir else None
        browser = BrowserSession(self.config, run_dir) if with_browser else None
        llm = self.llm_factory(self.config)
        executor = ToolExecutor(tools, browser=browser, workspace=workspace,
                                no_change_limit=int(self.config.get("no_change_limit", 3)), log=self.log)
        t0 = time.monotonic()
        try:
            if browser:
                browser.start()
            loop = AgentLoop(llm, executor, tools, int(self.config.get("debug_max_iterations", 25)), log=self.log)
            result = loop.run(read_prompt("debug_prompt.txt"), brief)
            diagnostics = {"http_errors": browser.http_errors(), "console": browser.console} if browser else {}
            screenshots = list(browser.screenshots) if browser else []
        finally:
            if browser:
                browser.close()
        status = "DIAGNOSED" if executor.final else ("ERROR" if result.stop_reason in ("llm_error", "refusal") else "INCONCLUSIVE")
        report = {
            "title": f"Débug — {label}",
            "mode": "debug",
            "objective": brief.split("\n")[0],
            "verdict": {"status": status, "claimed": None, "overrides": []},
            "stop_reason": result.stop_reason,
            "iterations": result.iterations,
            "error": result.error,
            "final": executor.final,
            "final_text": result.final_text,
            "actions": executor.actions,
            "diagnostics": diagnostics,
            "screenshots": screenshots,
            "fixes": [f.__dict__ for f in workspace.fixes] if workspace else [],
            "usage": getattr(llm, "usage", None).as_dict() if getattr(llm, "usage", None) else None,
            "duration_s": round(time.monotonic() - t0, 1),
        }
        _, md_path = write_report(run_dir, report)
        final = executor.final or {}
        self.log(f"🔎 Diagnostic : {status}")
        if final.get("root_cause"):
            self.log(f"   Cause racine ({final.get('confidence', '?')}) : {final['root_cause']}")
        for f in report["fixes"]:
            self.log(f"   🩹 {f['path']} — {'appliqué' if f['applied'] else 'proposé'}")
        self.log(f"📄 Rapport : {md_path}")
        return report
