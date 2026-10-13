"""
Méta-tests déterministes (sans appel à l'API Claude).

Ils vérifient les garde-fous appliqués par le code : plafond d'itérations,
arrêt sur actions sans effet, requalification des faux positifs, confinement
des outils de code, qualité des rapports. Le modèle est remplacé par un script.
"""

import json
import urllib.request
from pathlib import Path

import pytest

from agent.loop import AgentLoop, ToolExecutor
from agent.runner import Runner
from agent.verdict import decide
from tools.browser import BrowserSession
from tools.code_tools import CodeWorkspace
from tools.schemas import tools_for

ROOT = Path(__file__).resolve().parents[2]
BROWSER_TOOLS = tools_for("browser")


@pytest.fixture
def browser(config, tmp_path, fixture_url):
    session = BrowserSession(config, tmp_path)
    session.start()
    yield session
    session.close()


def make_loop(llm, browser, max_iterations=15):
    executor = ToolExecutor(BROWSER_TOOLS, browser=browser, no_change_limit=3, log=lambda *_: None)
    return AgentLoop(llm, executor, BROWSER_TOOLS, max_iterations, log=lambda *_: None), executor


# ---------------------------------------------------------------- outils navigateur
def test_page_state_uses_accessibility_refs(browser, fixture_url):
    browser.navigate_to_url(fixture_url + "/login")
    state = browser.capture_page_state().text
    assert '[textbox] "Adresse e-mail"' in state
    assert '[button] "Se connecter"' in state


def test_stale_reference_is_reported(browser, fixture_url):
    browser.navigate_to_url(fixture_url + "/login")
    browser.capture_page_state()
    browser.navigate_to_url(fixture_url + "/dead")
    executor = ToolExecutor(BROWSER_TOOLS, browser=browser, log=lambda *_: None)
    outcome = executor.execute("click_element", {"element_id": "e5"})
    assert outcome.is_error and "capture_page_state" in outcome.text


def test_role_name_targeting_survives_css_mutation(browser, fixture_url):
    for _ in range(2):
        browser.navigate_to_url(fixture_url + "/mutating")
        browser.click_element("button:Ajouter au panier")
        assert "Article ajouté au panier" in browser.capture_page_state().text


def test_big_dom_state_stays_compact(browser, fixture_url):
    browser.navigate_to_url(fixture_url + "/big-dom")
    outcome = browser.capture_page_state()
    assert outcome.data["node_count"] > 5000
    assert len(outcome.text) < 8000  # ~2 000 jetons : sans risque pour la fenêtre de contexte
    assert '"Valider la sélection"' in outcome.text


def test_double_click_creates_single_order(browser, fixture_url):
    browser.navigate_to_url(fixture_url + "/order")
    browser.wait_for(text_visible="Commandes enregistrées")
    browser.click_element("button:Passer la commande", repeat=3)
    browser.wait_for(text_visible="enregistrée.")
    posts = [e for e in browser.network if e["method"] == "POST" and e["url"].endswith("/api/orders")]
    assert len(posts) == 1


# ---------------------------------------------------------------- garde-fous de boucle
def test_iteration_cap_is_enforced(browser, fixture_url, fake_llm):
    llm = fake_llm(
        [[("navigate_to_url", {"url": fixture_url + "/maze"})], [("capture_page_state", {})]], repeat_last=True)
    loop, _ = make_loop(llm, browser, max_iterations=15)
    result = loop.run("system", "go")
    assert result.stop_reason == "max_iterations"
    assert llm.calls == 15
    # Le modèle est prévenu avant le dernier tour.
    assert any(b.get("type") == "text" and "un seul tour" in b["text"] for b in llm.received[-1]["content"])


def test_no_progress_guard_stops_after_three_inert_actions(browser, fixture_url, fake_llm):
    click = [("click_element", {"element_id": "button:Valider"})]
    llm = fake_llm([[("navigate_to_url", {"url": fixture_url + "/dead"})], click, click, click,
                    [("report_result", {"status": "BLOCKED", "summary": "Bouton sans effet", "root_cause": "Aucun gestionnaire de clic."})]])
    loop, executor = make_loop(llm, browser)
    result = loop.run("system", "go")
    assert result.stop_reason == "finished"
    assert llm.calls == 5
    guard_msg = llm.received[-1]["content"][-1]
    assert guard_msg["type"] == "text" and "GARDE-FOU" in guard_msg["text"]
    assert decide(result.stop_reason, executor.final, executor.assertions, browser.http_errors(), []).status == "BLOCKED"


def test_guard_refuses_further_actions(browser, fixture_url, fake_llm):
    click = [("click_element", {"element_id": "button:Valider"})]
    llm = fake_llm([[("navigate_to_url", {"url": fixture_url + "/dead"})], click, click, click, click])
    loop, executor = make_loop(llm, browser)
    result = loop.run("system", "go")
    assert result.stop_reason == "no_progress"
    assert executor.actions[-1]["n"] == 4  # le 4e clic n'a pas été exécuté
    assert decide(result.stop_reason, executor.final, executor.assertions, [], []).status == "BLOCKED"


# ---------------------------------------------------------------- faux positifs
def test_visual_success_with_http_500_is_requalified(browser, fixture_url, fake_llm):
    llm = fake_llm([
        [("navigate_to_url", {"url": fixture_url + "/trap"})],
        [("fill_input", {"element_id": "label=Nom affiché", "value": "Nouveau Nom"}),
         ("click_element", {"element_id": "button:Enregistrer le profil"})],
        [("assert_condition", {"expectation": "Message de succès", "status": "PASSED", "reason": "Message affiché"}),
         ("report_result", {"status": "PASSED", "summary": "Profil enregistré"})],
    ])
    loop, executor = make_loop(llm, browser)
    result = loop.run("system", "go")
    verdict = decide(result.stop_reason, executor.final, executor.assertions, browser.http_errors(), [])
    assert verdict.claimed == "PASSED"
    assert verdict.status == "FAILED"
    assert any("Faux positif" in o for o in verdict.overrides)


def test_expected_http_errors_are_not_requalified():
    errors = [{"method": "POST", "url": "http://x/api/login", "status": 401, "type": "fetch", "mocked": False}]
    final = {"status": "PASSED", "summary": "Refus attendu"}
    asserts = [{"status": "PASSED", "expectation": "refus", "reason": "message affiché"}]
    assert decide("finished", final, asserts, errors, [401]).status == "PASSED"
    assert decide("finished", final, asserts, errors, []).status == "FAILED"


def test_mocked_errors_are_not_requalified():
    errors = [{"method": "GET", "url": "http://x/api/profile", "status": 500, "type": "fetch", "mocked": True}]
    final = {"status": "PASSED", "summary": "Message d'erreur affiché"}
    asserts = [{"status": "PASSED", "expectation": "message", "reason": "ok"}]
    assert decide("finished", final, asserts, errors, []).status == "PASSED"


def test_passed_without_assertion_is_inconclusive():
    assert decide("finished", {"status": "PASSED", "summary": "ok"}, [], [], []).status == "INCONCLUSIVE"


# ---------------------------------------------------------------- outils de code
def test_code_tools_are_confined(tmp_path):
    (tmp_path / "app.js").write_text("const x = 1;\n")
    ws = CodeWorkspace(tmp_path, apply=False, backup_dir=tmp_path / "bk")
    executor = ToolExecutor(tools_for("code"), workspace=ws, log=lambda *_: None)
    outcome = executor.execute("read_source_file", {"path": "../../etc/passwd"})
    assert outcome.is_error and "hors du dossier source" in outcome.text


def test_fix_is_proposed_then_applied(tmp_path):
    src = tmp_path / "app.js"
    src.write_text("if (r.ok || true) { showSuccess(); }\n")
    ws = CodeWorkspace(tmp_path, apply=False, backup_dir=tmp_path / "bk")
    ws.propose_fix("app.js", "r.ok || true", "r.ok", "Le succès ne doit dépendre que du statut HTTP.")
    assert "r.ok || true" in src.read_text()
    assert ws.fixes[0].diff.startswith("--- a/app.js")

    ws_apply = CodeWorkspace(tmp_path, apply=True, backup_dir=tmp_path / "bk")
    ws_apply.propose_fix("app.js", "r.ok || true", "r.ok", "idem")
    assert src.read_text() == "if (r.ok) { showSuccess(); }\n"
    assert Path(ws_apply.fixes[0].backup).read_text() == "if (r.ok || true) { showSuccess(); }\n"


# ---------------------------------------------------------------- rapport (§5.4)
def test_report_contains_actions_screenshots_and_root_cause(config, tmp_path, fixture_url, fake_llm):
    click = [("click_element", {"element_id": "button:Valider"})]
    llm = fake_llm([[("navigate_to_url", {"url": fixture_url + "/dead"})], click, click, click,
                    [("report_result", {"status": "BLOCKED", "summary": "Bouton inerte",
                                        "root_cause": "Aucun gestionnaire d'événement n'est attaché au bouton 'Valider'.",
                                        "evidence": ["3 clics sans changement du DOM ni requête réseau"]})]])
    runner = Runner(config, log=lambda *_: None, llm_factory=lambda cfg: llm)
    result = runner.run_scenario(ROOT / "scenarios" / "33_eval_bouton_inerte.json", run_base=tmp_path)
    report = json.loads((Path(result["report"]).parent / "report.json").read_text())
    assert result["status"] == "BLOCKED" and result["eval_conform"] is True
    assert [a["tool"] for a in report["actions"]] == ["navigate_to_url"] + ["click_element"] * 3 + ["report_result"]
    assert report["final"]["root_cause"]
    assert report["screenshots"], "une capture de l'état final est attendue en cas d'échec"
    md = Path(result["report"]).read_text()
    for section in ("## Cause racine", "## Actions", "## Captures d'écran"):
        assert section in md


def test_secrets_are_redacted_from_reports(config, tmp_path, fixture_url, fake_llm):
    llm = fake_llm([
        [("navigate_to_url", {"url": fixture_url + "/login"})],
        [("fill_input", {"element_id": "label=Adresse e-mail", "value": "user@test.com"}),
         ("fill_input", {"element_id": "label=Mot de passe", "value": "Password123!"}),
         ("click_element", {"element_id": "button:Se connecter"})],
        [("assert_condition", {"expectation": "Tableau de bord", "status": "PASSED", "reason": "URL /dashboard"}),
         ("report_result", {"status": "PASSED", "summary": "Connexion OK"})],
    ])
    runner = Runner(config, log=lambda *_: None, llm_factory=lambda cfg: llm)
    result = runner.run_scenario(ROOT / "scenarios" / "01_e2e_auth_nominal.json", run_base=tmp_path)
    assert result["status"] == "PASSED"
    raw = (Path(result["report"]).parent / "report.json").read_text()
    assert "Password123!" not in raw


# ---------------------------------------------------------------- scénarios
def test_scenarios_are_well_formed():
    files = sorted((ROOT / "scenarios").glob("*.json"))
    assert len(files) >= 30
    ids = set()
    for f in files:
        s = json.loads(f.read_text())
        for key in ("id", "name", "priority", "target_url", "objective", "success_criteria"):
            assert s.get(key), f"{f.name} : champ {key} manquant"
        assert s["id"] not in ids
        ids.add(s["id"])
    references = {json.loads(f.read_text()).get("reference") for f in files}
    for section in ("§1.1", "§1.2", "§1.3", "§1.4", "§2.1", "§2.2", "§2.3", "§2.4", "§3.1", "§3.2", "§3.3",
                    "§4.1", "§4.2", "§4.3", "§5.1", "§5.2", "§5.3", "§5.4"):
        assert section in references, f"section {section} du référentiel non couverte"


def test_fixture_server_trap_returns_500(fixture_url):
    req = urllib.request.Request(fixture_url + "/api/save", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 500


# ---------------------------------------------------------------- chaîne test → correctif
def test_failed_test_chains_into_fix_proposal(config, tmp_path, fixture_url, fake_llm):
    app = tmp_path / "app"
    app.mkdir()
    (app / "profile.js").write_text("await fetch('/api/save');\nshowSuccess();\n")
    test_llm = fake_llm([
        [("navigate_to_url", {"url": fixture_url + "/trap"})],
        [("click_element", {"element_id": "button:Enregistrer le profil"})],
        [("report_result", {"status": "FAILED", "summary": "API 500", "root_cause": "POST /api/save renvoie 500 mais l'UI affiche un succès."})],
    ])
    fix_llm = fake_llm([
        [("search_code", {"pattern": "showSuccess"})],
        [("propose_fix", {"path": "profile.js", "old_string": "await fetch('/api/save');\nshowSuccess();",
                          "new_string": "const r = await fetch('/api/save');\nif (r.ok) showSuccess(); else showError(r.status);",
                          "rationale": "Le succès doit dépendre du statut HTTP."})],
        [("report_diagnosis", {"summary": "Succès affiché sans contrôle", "root_cause": "profile.js:2", "confidence": "haute"})],
    ])
    llms = iter([test_llm, fix_llm])
    runner = Runner(config, source_dir=app, log=lambda *_: None, llm_factory=lambda cfg: next(llms))
    result = runner.run_scenario(ROOT / "scenarios" / "32_eval_faux_positif.json", run_base=tmp_path / "reports")
    report = json.loads((Path(result["report"]).parent / "report.json").read_text())
    assert result["status"] == "FAILED"
    assert report["fixes"] and report["fixes"][0]["applied"] is False
    assert "if (r.ok)" in report["fixes"][0]["diff"]
    assert "showSuccess();\n" in (app / "profile.js").read_text()  # non appliqué sans --apply
