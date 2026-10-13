# Claude QA Testing Agent

Agent autonome de tests utilisateurs (E2E / Playwright), de diagnostic de cause racine et de correction de code, invocable en ligne de commande.

## Installation

```bash
pip install -r requirements.txt
python -m playwright install chromium   # ou PLAYWRIGHT_CHROMIUM_EXECUTABLE=/chemin/vers/chromium
cp .env.example .env                    # renseigner ANTHROPIC_API_KEY, puis APP_BASE_URL pour une application réelle
```

## Utilisation

| Besoin | Commande |
|---|---|
| Exécuter un test | `python src/main.py --scenario scenarios/01_e2e_auth_nominal.json` |
| Exécuter toute la suite | `python src/main.py --run-all` |
| Diagnostiquer une URL | `python src/main.py --debug https://staging.exemple.fr/panier --source-dir ../mon-app` |
| Diagnostiquer un fichier | `python src/main.py --debug ../mon-app/src/api/orders.js` |
| Tester puis corriger en cas d'échec | `python src/main.py --scenario <fichier> --source-dir ../mon-app` |
| Écrire les correctifs sur disque | ajouter `--apply` (sinon : diff dans le rapport) |

Codes de sortie : `0` succès · `1` test en échec · `2` argument invalide · `3` erreur API Claude · `4` navigateur introuvable.

Rapports : `reports/<horodatage>_<id>/report.md` (+ `report.json`, `screenshots/`).

## Fonctionnement

1. **Boucle** (`src/agent/loop.py`) : Claude reçoit le scénario, appelle des outils (`navigate_to_url`, `capture_page_state`, `click_element`…), le runner les exécute dans Playwright et renvoie les résultats, jusqu'à `report_result`.
2. **Garde-fous appliqués par le code** : 15 itérations maximum ; arrêt après 3 actions consécutives sans effet observable.
3. **Verdict recoupé** (`src/agent/verdict.py`) : un PASSED annoncé est requalifié s'il manque d'assertions ou si une erreur HTTP non attendue a eu lieu (faux positif visuel).
4. **Débug & correction** : avec `--source-dir`, l'agent lit le code (accès confiné à ce dossier), localise la cause racine et propose un correctif sous forme de diff.

## Scénarios

36 scénarios couvrent les 18 sections du référentiel `docs/listing-tests-agent-claude.pdf` :

- **Banc d'essai** (`${FIXTURE_BASE_URL}`, démarré automatiquement) : résilience, API, sécurité, méta-tests. Ces scénarios portent un `expected_verdict` et servent à évaluer l'agent lui-même.
- **Application réelle** (`${APP_BASE_URL}`) : panier, paiement, recherche, wizard, upload… Ils sont ignorés (SKIPPED) tant que `APP_BASE_URL` n'est pas défini, et leurs étapes sont à adapter à l'application cible.

## Tests

```bash
pytest tests/evals/            # 19 méta-tests déterministes, sans appel API
pytest tests/evals/ -m live    # evals de bout en bout avec Claude (consomment des jetons)
```

## Déploiement Railway

Projet Railway `agent-ia-test`, environnement `dev`, service `qa-agent` (build `Dockerfile`, config `railway.json`).

- **Déclenchement** : chaque push sur la branche suivie reconstruit l'image et lance une exécution. Pour relancer sans push : « Redeploy » dans le tableau de bord.
- **Une exécution** = méta-tests de l'image, puis `python src/main.py $AGENT_ARGS` si `ANTHROPIC_API_KEY` est défini. Le conteneur s'arrête ensuite (pas de redémarrage automatique).
- **Variables** : `AGENT_ARGS` (défaut `--run-all --filter eval`), `ANTHROPIC_API_KEY` (à saisir dans le tableau de bord), `APP_BASE_URL` et identifiants pour une application réelle.
- **Rapports** : volume `qa-reports` monté sur `/app/reports`.
- **Exécution planifiée** : renseigner un « Cron Schedule » sur le service (chaque exécution consomme des jetons Claude).

## Base de données (Supabase cloud) et migrations

- **Supabase** : projet `agent-ia-test` (réf. `dvssyttbibnqwqjetarm`, région Paris `eu-west-3`), organisation « Le Prompteur », offre gratuite. URL : `https://dvssyttbibnqwqjetarm.supabase.co` (variables partagées Railway `SUPABASE_URL`, `SUPABASE_PROJECT_REF`).
- **Redis** : service Railway `Redis` dans l'environnement `dev` (`REDIS_URL` via variable de référence `${{Redis.REDIS_URL}}`).
- **Migrations** : fichiers SQL horodatés dans `supabase/migrations/` (`supabase migration new <nom>`). Ne jamais modifier le schéma depuis le tableau de bord : toute modification passe par une migration versionnée.
- **Workflow `.github/workflows/db-migrations.yml`** :
  - PR modifiant `supabase/migrations/**` → simulation puis application sur la base de dev (secret `SUPABASE_DEV_DB_URL`) ;
  - merge sur `main` → application sur la production (secret `SUPABASE_PROD_DB_URL`, environnement GitHub `production` à protéger par une validation manuelle) ;
  - exécutions sérialisées par base ; PR issues de forks ignorées (pas d'accès aux secrets).
- **Secret GitHub à créer** (Settings → Secrets and variables → Actions) : `SUPABASE_DEV_DB_URL` = chaîne « Session pooler » du projet (Supabase → Connect → Session pooler, port 5432), mot de passe inclus. La connexion directe `db.<ref>.supabase.co` est en IPv6 seulement et n'est pas joignable depuis les runners GitHub.
- Une migration appliquée n'est pas annulée automatiquement : pour revenir en arrière, écrire une nouvelle migration inverse.
