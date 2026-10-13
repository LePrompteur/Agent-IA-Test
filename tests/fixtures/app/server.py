"""
Application de démonstration (banc d'essai de l'agent).

Elle ne sert pas à tester une application réelle : elle fournit des pièges dont
la réponse est connue d'avance, pour vérifier que l'agent se comporte comme
prévu (faux positifs, bouton inerte, latence, overlays, DOM volumineux…).

Lancement manuel : python -m tests.fixtures.app.server --port 8765
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VALID_EMAIL = "user@test.com"
VALID_PASSWORD = "Password123!"

SESSIONS: dict[str, dict] = {}
LOCK = threading.Lock()

BASE_CSS = """
body{font-family:system-ui,sans-serif;margin:0;padding:16px;max-width:960px}
header{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px}
.alert{padding:8px 12px;border-radius:6px;margin:8px 0}.err{background:#fde2e2}.ok{background:#e2f7e2}
.spinner{font-style:italic;color:#666}
button{padding:6px 12px}
"""


def page(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{BASE_CSS}</style></head><body>{body}<script>{script}</script></body></html>"""


PAGES: dict[str, str] = {}

PAGES["/"] = page("Banc d'essai", """<h1>Banc d'essai de l'agent</h1><ul>
<li><a href="/login">Connexion</a></li><li><a href="/trap">Piège faux positif</a></li>
<li><a href="/dead">Bouton inerte</a></li><li><a href="/slow">Chargement lent</a></li>
<li><a href="/cookies">Bandeau RGPD</a></li><li><a href="/promo">Popup promotionnelle</a></li>
<li><a href="/mutating">DOM muté</a></li><li><a href="/flaky">DOM re-rendu</a></li>
<li><a href="/big-dom">DOM volumineux</a></li><li><a href="/responsive">Responsive</a></li>
<li><a href="/profile">Profil (API)</a></li><li><a href="/order">Commande</a></li>
<li><a href="/comment">Commentaires</a></li><li><a href="/maze">Labyrinthe</a></li></ul>""")

PAGES["/login"] = page("Connexion", """
<h1>Connexion</h1>
<form id="f" novalidate>
  <p><label for="email">Adresse e-mail</label><br><input id="email" name="email" type="email" required></p>
  <p><label for="pwd">Mot de passe</label><br><input id="pwd" name="password" type="password" required></p>
  <button type="submit">Se connecter</button>
</form>
<div id="msg" role="alert"></div>""", """
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const r = await fetch('/api/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: email.value, password: pwd.value})});
  if (r.ok) { const d = await r.json(); localStorage.setItem('auth_token', d.token); location.href = '/dashboard'; }
  else { msg.className = 'alert err'; msg.textContent = 'Identifiant ou mot de passe incorrect.'; }
});""")

PAGES["/dashboard"] = page("Tableau de bord", """
<header><h1>Tableau de bord</h1><button id="logout">Se déconnecter</button></header>
<p>Bienvenue, Utilisateur Test !</p>""", """
logout.onclick = async () => { await fetch('/api/logout', {method: 'POST'}); localStorage.clear(); sessionStorage.clear(); location.replace('/login'); };""")

PAGES["/trap"] = page("Profil", """
<h1>Mon profil</h1>
<p><label for="name">Nom affiché</label><br><input id="name" value="Utilisateur Test"></p>
<button id="save">Enregistrer le profil</button>
<div id="msg" role="status"></div>""", """
// Défaut volontaire : le message de succès est affiché sans vérifier la réponse HTTP.
save.onclick = async () => {
  try { await fetch('/api/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: name.value})}); } catch (e) {}
  msg.className = 'alert ok'; msg.textContent = 'Profil enregistré avec succès.';
};""")

PAGES["/dead"] = page("Validation", """
<h1>Valider la demande</h1><p>Cliquez sur Valider pour confirmer votre demande.</p>
<button id="go">Valider</button><div id="msg" role="status"></div>""", """
// Défaut volontaire : aucun gestionnaire n'est branché sur le bouton.""")

PAGES["/slow"] = page("Résultats", """
<h1>Recherche</h1><p id="spin" class="spinner" role="status">Chargement…</p><div id="zone"></div><div id="msg" role="status"></div>""", """
setTimeout(() => {
  spin.remove();
  const b = document.createElement('button'); b.textContent = 'Afficher les résultats';
  b.onclick = async () => { const r = await fetch('/api/results'); const d = await r.json(); msg.textContent = d.count + ' résultats chargés'; };
  zone.appendChild(b);
}, 4000);""")

COOKIE_BANNER = """
<div id="rgpd" style="position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:flex-end;z-index:1000">
  <div role="dialog" aria-modal="true" aria-label="Gestion des cookies" style="background:#fff;width:100%;padding:24px">
    <p>Nous utilisons des cookies pour améliorer votre expérience.</p>
    <button onclick="rgpd.remove()">Tout accepter</button> <button onclick="rgpd.remove()">Refuser</button>
  </div></div>"""

NEWSLETTER = """
<h1>Newsletter</h1><p><label for="nl">E-mail</label> <input id="nl" type="email"></p>
<button id="sub">S'abonner</button><div id="msg" role="status"></div>"""

NEWSLETTER_JS = """sub.onclick = async () => { const r = await fetch('/api/subscribe', {method: 'POST', body: nl.value});
  msg.textContent = r.ok ? 'Abonnement confirmé.' : 'Erreur.'; };"""

PAGES["/cookies"] = page("Newsletter", NEWSLETTER + COOKIE_BANNER, NEWSLETTER_JS)

PAGES["/promo"] = page("Newsletter", NEWSLETTER, NEWSLETTER_JS + """
setTimeout(() => {
  const d = document.createElement('div');
  d.id = 'promo';
  d.innerHTML = '<div role="dialog" aria-modal="true" aria-label="Offre spéciale" style="position:fixed;inset:20% 25%;background:#fff;border:2px solid #333;padding:24px;z-index:1000"><h2>-20 % aujourd\\'hui !</h2><button aria-label="Fermer la fenêtre promotionnelle" onclick="promo.remove()">×</button></div><div style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:999"></div>';
  document.body.appendChild(d);
}, 1500);""")

PAGES["/mutating"] = page("Boutique", """
<h1>Chaussures de randonnée</h1><div id="wrap" style="display:flex;flex-wrap:wrap;gap:12px"></div><div id="msg" role="status"></div>""", """
// Classes, identifiants et position changent à chaque chargement ; seul le rôle et le libellé sont stables.
const rnd = () => 'x' + Math.random().toString(36).slice(2, 8);
const parts = ['<p>Prix : 89 €</p>', '<button class="' + rnd() + '" id="' + rnd() + '">Ajouter au panier</button>', '<p>Livraison offerte</p>'];
parts.sort(() => Math.random() - .5);
wrap.innerHTML = parts.join('');
wrap.style.flexDirection = Math.random() > .5 ? 'row' : 'column-reverse';
let n = 0;
wrap.addEventListener('click', e => { if (e.target.tagName === 'BUTTON') { n++; msg.textContent = 'Article ajouté au panier (' + n + ')'; } });""")

PAGES["/flaky"] = page("Code promo", """
<h1>Panier</h1><div id="form"></div><div id="msg" role="status"></div>""", """
// Le formulaire est re-rendu toutes les 2 s (nœuds recréés) : les références capturées deviennent obsolètes.
let code = '';
function render() {
  form.innerHTML = '<label for="c' + Date.now() + '">Code promo</label> <input id="c' + Date.now() + '"> <button type="button">Appliquer</button>';
  const i = form.querySelector('input'); i.value = code; i.oninput = () => code = i.value;
  form.querySelector('button').onclick = () => { msg.textContent = code.trim().toUpperCase() === 'PROMO10' ? 'Code PROMO10 appliqué : -10 %' : 'Code invalide'; };
}
render(); setInterval(render, 2000);""")

_rows = "".join(
    f"<tr><td>REF-{i:04d}</td><td><span>Produit {i}</span></td><td><span>{(i * 7) % 100} €</span></td><td><span>Stock {(i * 13) % 50}</span></td></tr>"
    for i in range(1, 1201)
)
PAGES["/big-dom"] = page("Catalogue", f"""
<h1>Catalogue complet</h1>
<p><button id="ok">Valider la sélection</button></p><div id="msg" role="status"></div>
<table><tbody>{_rows}</tbody></table>""", "ok.onclick = () => msg.textContent = 'Sélection validée.';")

PAGES["/responsive"] = page("Accueil", """
<style>
nav ul{display:flex;gap:16px;list-style:none;padding:0}
#burger{display:none}
@media (max-width:767px){#burger{display:inline-block} nav ul{display:none;flex-direction:column} nav.open ul{display:flex}}
</style>
<header><strong>Logo</strong><nav id="nav" aria-label="Navigation principale">
<button id="burger" aria-expanded="false" aria-controls="menu" aria-label="Menu">☰</button>
<ul id="menu"><li><a href="/responsive">Accueil</a></li><li><a href="/contact">Contact</a></li><li><a href="/responsive#offres">Offres</a></li></ul></nav></header>
<h1>Bienvenue</h1><p>Site vitrine de démonstration.</p>""", """
burger.onclick = () => { nav.classList.toggle('open'); burger.setAttribute('aria-expanded', nav.classList.contains('open')); };""")

PAGES["/contact"] = page("Contact", "<h1>Page Contact</h1><p>Écrivez-nous à contact@example.test</p>")

PAGES["/profile"] = page("Profil", """
<h1>Profil</h1><div id="offline" role="alert" hidden class="alert err">Vous êtes hors ligne. Certaines fonctions sont indisponibles.</div>
<div id="out" role="status">Chargement…</div><button id="retry">Réessayer</button>""", """
async function load() {
  out.className = ''; out.textContent = 'Chargement…';
  try {
    const r = await fetch('/api/profile');
    if (!r.ok) { out.className = 'alert err'; out.textContent = 'Impossible de charger le profil (erreur ' + r.status + '). Réessayez plus tard.'; return; }
    const d = await r.json(); out.textContent = 'Nom : ' + d.name + ' — Rôle : ' + d.role;
  } catch (e) { out.className = 'alert err'; out.textContent = 'Connexion au serveur impossible.'; }
}
retry.onclick = load; load();
addEventListener('offline', () => offline.hidden = false);
addEventListener('online', () => { offline.hidden = true; load(); });""")

PAGES["/order"] = page("Commande", """
<h1>Récapitulatif</h1><p>1 × Sac à dos — 59 €</p>
<button id="pay">Passer la commande</button><div id="msg" role="status"></div><p id="count"></p>""", """
async function refresh() { const r = await fetch('/api/orders'); const d = await r.json(); count.textContent = 'Commandes enregistrées : ' + d.count; }
pay.onclick = async () => {
  pay.disabled = true; msg.textContent = 'Traitement…';
  const r = await fetch('/api/orders', {method: 'POST'});
  const d = await r.json(); msg.textContent = 'Commande n°' + d.id + ' enregistrée.';
  await refresh();
};
refresh();""")

PAGES["/comment"] = page("Commentaires", """
<h1>Commentaires</h1>
<p><label for="txt">Votre commentaire</label><br><textarea id="txt" rows="4" cols="60"></textarea></p>
<button id="pub">Publier</button><div id="msg" role="alert"></div><ul id="list" aria-label="Commentaires publiés"></ul>""", """
pub.onclick = async () => {
  const r = await fetch('/api/comments', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: txt.value})});
  const d = await r.json();
  if (!r.ok) { msg.className = 'alert err'; msg.textContent = d.error; return; }
  msg.className = ''; msg.textContent = '';
  const li = document.createElement('li'); li.textContent = d.text; list.appendChild(li);  // textContent : échappement
};""")


def maze_page(n: int) -> str:
    return page(f"Archives — page {n}", f"""
<h1>Archives — page {n}</h1><p>Document {n * 3 - 2}, document {n * 3 - 1}, document {n * 3}.</p>
<a href="/maze?page={n + 1}">Page suivante</a>""")


class Handler(BaseHTTPRequestHandler):
    server_version = "FixtureApp/1.0"

    def log_message(self, *args):  # silencieux
        pass

    # ------------------------------------------------------------------ utilitaires
    def _session(self) -> tuple[str | None, dict | None]:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie["session"].value if "session" in cookie else None
        with LOCK:
            return token, SESSIONS.get(token) if token else None

    def _send(self, status: int, body: str | bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: dict, headers: dict | None = None):
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8", headers)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/dashboard":
            _, sess = self._session()
            if not sess:
                return self._send(302, "", headers={"Location": "/login"})
        if url.path == "/maze":
            n = int(parse_qs(url.query).get("page", ["1"])[0])
            return self._send(200, maze_page(n))
        if url.path in PAGES:
            return self._send(200, PAGES[url.path])
        if url.path == "/api/results":
            return self._json(200, {"count": 42})
        if url.path == "/api/profile":
            return self._json(200, {"name": "Utilisateur Test", "role": "Locataire"})
        if url.path == "/api/orders":
            token, sess = self._session()
            return self._json(200, {"count": len((sess or {}).get("orders", []))})
        return self._send(404, page("Introuvable", "<h1>404 — Page introuvable</h1>"))

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        if url.path == "/api/login":
            try:
                data = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "JSON invalide"})
            if data.get("email") == VALID_EMAIL and data.get("password") == VALID_PASSWORD:
                token = secrets.token_hex(16)
                with LOCK:
                    SESSIONS[token] = {"orders": []}
                return self._json(200, {"token": token}, {"Set-Cookie": f"session={token}; Path=/; HttpOnly; SameSite=Lax"})
            return self._json(401, {"error": "Identifiants invalides"})
        if url.path == "/api/logout":
            token, _ = self._session()
            with LOCK:
                SESSIONS.pop(token, None)
            return self._json(200, {"ok": True}, {"Set-Cookie": "session=; Path=/; Max-Age=0"})
        if url.path == "/api/save":
            return self._json(500, {"error": "Internal Server Error: database connection lost"})
        if url.path == "/api/subscribe":
            return self._json(201, {"ok": True})
        if url.path == "/api/orders":
            token, sess = self._session()
            if not sess:
                token = secrets.token_hex(16)
                sess = {"orders": []}
                with LOCK:
                    SESSIONS[token] = sess
            time.sleep(1.0)  # traitement lent : fenêtre pour la double soumission
            with LOCK:
                sess["orders"].append(len(sess["orders"]) + 1)
                order_id = 1000 + len(sess["orders"])
            return self._json(201, {"id": order_id}, {"Set-Cookie": f"session={token}; Path=/; SameSite=Lax"})
        if url.path == "/api/comments":
            try:
                data = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "Requête mal formée."})
            text = str(data.get("text", ""))
            if not text.strip():
                return self._json(422, {"error": "Le commentaire est vide."})
            if len(text) > 5000:
                return self._json(413, {"error": "Commentaire trop long (5000 caractères maximum)."})
            return self._json(201, {"text": text})
        return self._json(404, {"error": "Route inconnue"})


@dataclass
class FixtureServer:
    server: ThreadingHTTPServer
    thread: threading.Thread

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def start_fixture_server(host: str = "127.0.0.1", port: int = 0) -> FixtureServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return FixtureServer(server, thread)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    srv = start_fixture_server(port=args.port)
    print(f"Application de démonstration : {srv.base_url}  (Ctrl+C pour arrêter)")
    try:
        srv.thread.join()
    except KeyboardInterrupt:
        srv.stop()
