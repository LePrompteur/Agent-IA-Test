"""
Exécution mécanique des outils navigateur (Playwright, API synchrone).

Aucune décision ici : chaque méthode exécute une action, journalise et renvoie
un résultat factuel que l'agent interprète.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ARIA_ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox", "option",
    "menuitem", "tab", "switch", "slider", "searchbox", "heading", "dialog", "img",
    "navigation", "row", "cell", "spinbutton",
}

API_RESOURCE_TYPES = {"xhr", "fetch"}
SAFE_HEADERS = {"content-type", "accept", "authorization", "x-requested-with", "x-csrf-token"}

# Script d'extraction de l'état de page : pose un attribut data-qa-ref sur chaque
# élément visible et calcule un nom accessible simplifié.
PAGE_STATE_JS = r"""
({maxItems, maxText}) => {
  const SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role],[tabindex]:not([tabindex="-1"]),[contenteditable="true"],h1,h2,h3';
  const txt = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const nameOf = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(e => e.innerText).join(' ');
      if (txt(t)) return txt(t).slice(0, 100);
    }
    if (el.getAttribute('aria-label')) return txt(el.getAttribute('aria-label')).slice(0, 100);
    if (el.labels && el.labels.length) return txt([...el.labels].map(l => l.innerText).join(' ')).slice(0, 100);
    if (el.tagName === 'IMG') return txt(el.alt);
    if (el.tagName !== 'SELECT' && el.tagName !== 'TEXTAREA') {
      const t = txt(el.innerText || '');
      if (t) return t.slice(0, 100);
    }
    return txt(el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || (el.tagName === 'INPUT' && ['submit', 'button'].includes(el.type) ? el.value : '') || '').slice(0, 100);
  };
  const ROLE_BY_TAG = {A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox', SUMMARY: 'button', H1: 'heading', H2: 'heading', H3: 'heading'};
  const INPUT_ROLES = {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', reset: 'button', file: 'file-input', range: 'slider', search: 'searchbox', number: 'spinbutton'};
  const roleOf = el => el.getAttribute('role') || ROLE_BY_TAG[el.tagName] || (el.tagName === 'INPUT' ? (INPUT_ROLES[el.type] || 'textbox') : el.tagName.toLowerCase());

  document.querySelectorAll('[data-qa-ref]').forEach(e => e.removeAttribute('data-qa-ref'));
  const items = [];
  let total = 0;
  for (const el of document.querySelectorAll(SEL)) {
    if (!visible(el)) continue;
    total++;
    if (items.length >= maxItems) continue;
    const ref = 'e' + (items.length + 1);
    el.setAttribute('data-qa-ref', ref);
    const it = {ref, role: roleOf(el), name: nameOf(el)};
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
      if (['checkbox', 'radio'].includes(el.type)) it.checked = el.checked;
      else if (el.type === 'password') it.value = el.value ? '***' : '';
      else if (!['submit', 'button', 'file', 'reset'].includes(el.type)) it.value = String(el.value).slice(0, 80);
      if (el.required) it.required = true;
      if (el.getAttribute('aria-invalid') === 'true') it.invalid = true;
    }
    if (el.tagName === 'SELECT') it.options = [...el.options].slice(0, 25).map(o => o.text);
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') it.disabled = true;
    if (el.getAttribute('aria-expanded')) it.expanded = el.getAttribute('aria-expanded');
    if (el.tagName === 'A') it.href = el.getAttribute('href');
    items.push(it);
  }
  const alerts = [...document.querySelectorAll('[role=alert],[role=status],[aria-live],dialog[open],[role=dialog],[role=alertdialog],[aria-modal=true]')]
    .filter(visible).slice(0, 10)
    .map(e => ({role: e.getAttribute('role') || e.tagName.toLowerCase(), text: txt(e.innerText).slice(0, 300)}));
  const overlays = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    const cover = (r.width * r.height) / (innerWidth * innerHeight);
    if (cover > 0.15) overlays.push({ref: el.getAttribute('data-qa-ref'), coverage: Math.round(cover * 100) + '%', text: txt(el.innerText).slice(0, 150)});
    if (overlays.length >= 5) break;
  }
  const body = txt(document.body ? document.body.innerText : '');
  return {
    title: document.title, items, total_interactive: total, alerts, overlays,
    text: body.slice(0, maxText), text_truncated: body.length > maxText,
    node_count: document.getElementsByTagName('*').length,
  };
}
"""


@dataclass
class ToolOutcome:
    """Résultat d'un appel d'outil, renvoyé à Claude sous forme de tool_result."""

    text: str
    is_error: bool = False
    image_b64: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_content(self) -> list[dict] | str:
        if not self.image_b64:
            return self.text
        return [
            {"type": "text", "text": self.text},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": self.image_b64}},
        ]


class ToolInputError(ValueError):
    pass


class BrowserLaunchError(RuntimeError):
    pass


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + f"… [{len(value) - limit} caractères tronqués]"


def resolve_chromium_executable(configured: str | None) -> str | None:
    """Chemin explicite du binaire Chromium (config, puis variable d'environnement)."""
    path = configured or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return path if path and Path(path).exists() else None


class BrowserSession:
    """Session Playwright instrumentée : console, réseau, captures."""

    def __init__(self, config: dict, artifacts_dir: Path):
        self.config = config
        self.artifacts_dir = artifacts_dir
        self.screenshots_dir = artifacts_dir / "screenshots"
        upload_dir = Path(config.get("upload_dir", "tests/fixtures/uploads"))
        self.upload_dir = (upload_dir if upload_dir.is_absolute() else PROJECT_ROOT / upload_dir).resolve()
        self.action_timeout_ms = int(config.get("action_timeout_ms", 5000))
        self.max_state_items = int(config.get("max_state_items", 150))
        self.max_state_text = int(config.get("max_state_text_chars", 3000))
        self.console: list[dict] = []
        self.network: list[dict] = []
        self.mocked_patterns: list[str] = []
        self.screenshots: list[str] = []
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self._t0 = time.monotonic()

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        self._pw = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": self.config.get("headless", True)}
        executable = resolve_chromium_executable(self.config.get("browser_executable"))
        if executable:
            launch_kwargs["executable_path"] = executable
        try:
            self._browser = self._pw.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            self._pw.stop()
            self._pw = None
            raise BrowserLaunchError(
                "Impossible de lancer Chromium. Exécutez `python -m playwright install chromium`, "
                "ou indiquez un binaire existant via la variable PLAYWRIGHT_CHROMIUM_EXECUTABLE "
                f"(ou la clé browser_executable de config/config.json). Détail : {str(exc).splitlines()[0]}"
            ) from exc
        vp = self.config.get("viewport", {"width": 1280, "height": 720})
        self._context = self._browser.new_context(viewport=vp, ignore_https_errors=False)
        self._context.set_default_timeout(self.action_timeout_ms)
        self.page = self._context.new_page()
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda exc: self._log_console("pageerror", str(exc)))
        self.page.on("response", self._on_response)
        self.page.on("requestfailed", self._on_request_failed)

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except PlaywrightError:
                pass
        if self._pw:
            self._pw.stop()

    # ------------------------------------------------------------------ journaux
    def _elapsed(self) -> float:
        return round(time.monotonic() - self._t0, 2)

    def _log_console(self, level: str, text: str) -> None:
        self.console.append({"t": self._elapsed(), "level": level, "text": _truncate(text, 500)})

    def _on_console(self, msg) -> None:
        if msg.type in ("error", "warning"):
            self._log_console(msg.type, msg.text)

    def _is_mocked(self, url: str) -> bool:
        from fnmatch import fnmatch
        return any(fnmatch(url, p) for p in self.mocked_patterns)

    def _on_response(self, response) -> None:
        req = response.request
        headers = {k: v for k, v in req.headers.items() if k.lower() in SAFE_HEADERS}
        if "authorization" in headers:
            headers["authorization"] = headers["authorization"][:12] + "…"
        self.network.append({
            "t": self._elapsed(),
            "method": req.method,
            "url": response.url,
            "status": response.status,
            "type": req.resource_type,
            "request_headers": headers,
            "post_data": _truncate(req.post_data, 500),
            "mocked": self._is_mocked(response.url),
            "_response": response if req.resource_type in API_RESOURCE_TYPES else None,
        })

    def _on_request_failed(self, request) -> None:
        self.network.append({
            "t": self._elapsed(),
            "method": request.method,
            "url": request.url,
            "status": None,
            "type": request.resource_type,
            "failure": request.failure,
            "mocked": False,
            "_response": None,
        })

    def http_errors(self) -> list[dict]:
        return [
            {k: v for k, v in e.items() if not k.startswith("_")}
            for e in self.network
            if e.get("status") is None or e["status"] >= 400
        ]

    def screenshot(self, label: str) -> str | None:
        try:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            name = f"{len(self.screenshots) + 1:02d}_{re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:40]}.png"
            path = self.screenshots_dir / name
            self.page.screenshot(path=str(path), full_page=False)
            self.screenshots.append(str(path))
            return str(path)
        except PlaywrightError:
            return None

    # ------------------------------------------------------------------ état de page
    def page_state(self) -> dict:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.action_timeout_ms)
        except PlaywrightTimeout:
            pass
        state = self.page.evaluate(PAGE_STATE_JS, {"maxItems": self.max_state_items, "maxText": self.max_state_text})
        state["url"] = self.page.url
        return state

    def fingerprint(self) -> str:
        """Empreinte de l'état observable (garde-fou 'action sans effet')."""
        try:
            state = self.page_state()
        except PlaywrightError:
            return "unavailable"
        payload = json.dumps([state["url"], state["items"], state["alerts"], state["text"]], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def settle(self) -> None:
        """Laisse la page réagir à une action avant d'observer le résultat."""
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.action_timeout_ms)
        except PlaywrightTimeout:
            pass
        self.page.wait_for_timeout(int(self.config.get("settle_ms", 400)))

    # ------------------------------------------------------------------ localisation
    def locate(self, element_id: str):
        eid = (element_id or "").strip()
        if not eid:
            raise ToolInputError("element_id vide.")
        if re.fullmatch(r"e\d+", eid):
            loc = self.page.locator(f'[data-qa-ref="{eid}"]')
            if loc.count() == 0:
                raise ToolInputError(
                    f"Référence '{eid}' introuvable : la page a changé depuis la dernière capture. "
                    "Appelez capture_page_state pour obtenir des références à jour."
                )
            return loc.first
        m = re.fullmatch(r"([a-z]+):(.+)", eid)
        if m and m.group(1) in ARIA_ROLES:
            return self.page.get_by_role(m.group(1), name=m.group(2).strip()).first
        if eid.startswith("text="):
            return self.page.get_by_text(eid[5:].strip()).first
        if eid.startswith("label="):
            return self.page.get_by_label(eid[6:].strip()).first
        return self.page.locator(eid).first

    # ------------------------------------------------------------------ outils
    def navigate_to_url(self, url: str) -> ToolOutcome:
        if not re.match(r"^https?://", url or ""):
            raise ToolInputError("L'URL doit commencer par http:// ou https://.")
        resp = self.page.goto(url, wait_until="domcontentloaded", timeout=int(self.config.get("navigation_timeout_ms", 20000)))
        status = resp.status if resp else None
        return ToolOutcome(f"Page chargée. Statut HTTP du document : {status}. URL finale : {self.page.url}", is_error=bool(status and status >= 400))

    def capture_page_state(self, include_screenshot: bool = False) -> ToolOutcome:
        state = self.page_state()
        lines = [f"URL : {state['url']}", f"Titre : {state['title']}", f"Nœuds DOM : {state['node_count']}"]
        if state["overlays"]:
            lines.append("OVERLAYS potentiellement bloquants : " + json.dumps(state["overlays"], ensure_ascii=False))
        if state["alerts"]:
            lines.append("Alertes / dialogues : " + json.dumps(state["alerts"], ensure_ascii=False))
        shown = len(state["items"])
        lines.append(f"Éléments interactifs visibles ({shown} affichés sur {state['total_interactive']}) :")
        for it in state["items"]:
            extras = {k: v for k, v in it.items() if k not in ("ref", "role", "name")}
            lines.append(f"  {it['ref']} [{it['role']}] \"{it['name']}\"" + (f" {json.dumps(extras, ensure_ascii=False)}" if extras else ""))
        if state["total_interactive"] > shown:
            lines.append(f"  … {state['total_interactive'] - shown} éléments non listés (DOM volumineux) : ciblez-les par 'role:nom' ou 'text='.")
        lines.append("Texte visible" + (" (tronqué)" if state["text_truncated"] else "") + " :")
        lines.append(state["text"])
        image = None
        if include_screenshot:
            path = self.screenshot("state")
            if path:
                jpeg = self.page.screenshot(type="jpeg", quality=60)
                image = base64.b64encode(jpeg).decode()
                lines.append(f"Capture enregistrée : {path}")
        return ToolOutcome("\n".join(lines), image_b64=image, data={"node_count": state["node_count"]})

    def click_element(self, element_id: str, description: str | None = None, repeat: int = 1) -> ToolOutcome:
        loc = self.locate(element_id)
        repeat = max(1, min(int(repeat or 1), 5))
        if repeat == 1:
            loc.click()
            return ToolOutcome(f"Clic effectué sur '{element_id}'. URL : {self.page.url}")
        done = []
        for i in range(repeat):
            try:
                loc.click(timeout=600, no_wait_after=True)
                done.append(f"clic {i + 1} : effectué")
            except (PlaywrightTimeout, PlaywrightError) as exc:
                done.append(f"clic {i + 1} : refusé ({str(exc).splitlines()[0][:120]})")
        return ToolOutcome("Clics enchaînés : " + " ; ".join(done))

    def fill_input(self, element_id: str, value: str) -> ToolOutcome:
        self.locate(element_id).fill(value)
        return ToolOutcome(f"Champ '{element_id}' rempli ({len(value)} caractères).")

    def select_option(self, element_id: str, option: str) -> ToolOutcome:
        loc = self.locate(element_id)
        try:
            selected = loc.select_option(label=option)
        except (PlaywrightError, PlaywrightTimeout):
            selected = loc.select_option(value=option)
        return ToolOutcome(f"Option sélectionnée : {selected}")

    def upload_file(self, element_id: str, file_name: str) -> ToolOutcome:
        path = (self.upload_dir / file_name).resolve()
        if self.upload_dir not in path.parents or not path.is_file():
            available = sorted(p.name for p in self.upload_dir.glob("*") if p.is_file()) if self.upload_dir.exists() else []
            raise ToolInputError(f"Fichier non autorisé ou absent. Fichiers disponibles : {available}")
        self.locate(element_id).set_input_files(str(path))
        return ToolOutcome(f"Fichier '{file_name}' ({path.stat().st_size} octets) transmis au champ.")

    def press_key(self, key: str, element_id: str | None = None) -> ToolOutcome:
        if element_id:
            self.locate(element_id).press(key)
        else:
            self.page.keyboard.press(key)
        return ToolOutcome(f"Touche '{key}' envoyée.")

    def browser_navigation(self, action: str) -> ToolOutcome:
        if action == "back":
            resp = self.page.go_back(wait_until="domcontentloaded")
        elif action == "forward":
            resp = self.page.go_forward(wait_until="domcontentloaded")
        elif action == "reload":
            resp = self.page.reload(wait_until="domcontentloaded")
        else:
            raise ToolInputError("action doit valoir back, forward ou reload.")
        status = resp.status if resp else "aucune requête (cache ou pas d'historique)"
        return ToolOutcome(f"Navigation '{action}' effectuée. URL : {self.page.url}. Statut : {status}")

    def set_viewport(self, width: int, height: int) -> ToolOutcome:
        self.page.set_viewport_size({"width": int(width), "height": int(height)})
        return ToolOutcome(f"Viewport réglé sur {width}x{height}.")

    def wait_for(self, text_visible: str | None = None, text_hidden: str | None = None, timeout_seconds: float = 10) -> ToolOutcome:
        timeout_ms = int(min(float(timeout_seconds or 10), float(self.config.get("max_wait_seconds", 20))) * 1000)
        start = time.monotonic()
        try:
            if text_visible:
                self.page.get_by_text(text_visible).first.wait_for(state="visible", timeout=timeout_ms)
            if text_hidden:
                self.page.get_by_text(text_hidden).first.wait_for(state="hidden", timeout=timeout_ms)
            if not text_visible and not text_hidden:
                self.page.wait_for_timeout(timeout_ms)
        except PlaywrightTimeout:
            return ToolOutcome(f"Condition non remplie après {timeout_ms / 1000:.1f} s.", is_error=True)
        return ToolOutcome(f"Condition remplie après {time.monotonic() - start:.1f} s.")

    def get_console_logs(self) -> ToolOutcome:
        payload = {"console": self.console[-50:], "http_errors": self.http_errors()[-50:]}
        if not payload["console"] and not payload["http_errors"]:
            return ToolOutcome("Aucune erreur console ni erreur HTTP enregistrée.")
        return ToolOutcome(json.dumps(payload, ensure_ascii=False, indent=1))

    def get_network_log(self, url_contains: str | None = None, only_api: bool = True, last_n: int = 30) -> ToolOutcome:
        entries = [
            e for e in self.network
            if (not only_api or e["type"] in API_RESOURCE_TYPES)
            and (not url_contains or url_contains in e["url"])
        ][-int(last_n or 30):]
        out = []
        for e in entries:
            item = {k: v for k, v in e.items() if not k.startswith("_")}
            resp = e.get("_response")
            if resp is not None:
                try:
                    item["response_excerpt"] = _truncate(resp.text(), 400)
                except PlaywrightError:
                    item["response_excerpt"] = "(corps indisponible)"
            out.append(item)
        if not out:
            return ToolOutcome("Aucune requête correspondante.")
        return ToolOutcome(json.dumps(out, ensure_ascii=False, indent=1))

    def mock_http_response(self, url_pattern: str, status: int, body: str | None = None, content_type: str | None = None) -> ToolOutcome:
        def handler(route):
            route.fulfill(status=int(status), body=body or "", content_type=content_type or "application/json")
        self.page.route(url_pattern, handler)
        self.mocked_patterns.append(url_pattern)
        return ToolOutcome(f"Interception active : {url_pattern} → HTTP {status}.")

    def clear_http_mocks(self) -> ToolOutcome:
        self.page.unroute_all()
        self.mocked_patterns.clear()
        return ToolOutcome("Interceptions supprimées.")

    def set_network_offline(self, offline: bool) -> ToolOutcome:
        self._context.set_offline(bool(offline))
        return ToolOutcome("Réseau coupé." if offline else "Réseau rétabli.")

    def inspect_storage(self) -> ToolOutcome:
        cookies = [
            {"name": c["name"], "domain": c["domain"], "httpOnly": c["httpOnly"], "secure": c["secure"],
             "value": (c["value"][:4] + "…") if c["value"] else ""}
            for c in self._context.cookies()
        ]
        try:
            storage = self.page.evaluate("() => ({localStorage: Object.keys(localStorage), sessionStorage: Object.keys(sessionStorage)})")
        except PlaywrightError:
            storage = {"localStorage": "inaccessible", "sessionStorage": "inaccessible"}
        return ToolOutcome(json.dumps({"cookies": cookies, **storage}, ensure_ascii=False, indent=1))
