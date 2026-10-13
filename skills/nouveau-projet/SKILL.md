---
name: nouveau-projet
description: Crée un nouveau projet web de bout en bout, par étapes vérifiées — questions d'usage, dépôt GitHub privé, ossature Astro ou Next.js, première PR, service Railway relié à GitHub, premier déploiement contrôlé. À utiliser dès que l'utilisateur veut démarrer, initialiser ou « lancer » un nouveau site, une nouvelle application ou un nouveau projet de code à mettre en ligne, même s'il ne cite ni GitHub ni Railway (« nouveau projet », « je veux créer un site pour un client », « on démarre une app », « mets en place un dépôt et l'hébergement »). Ne pas utiliser pour modifier un projet existant déjà déployé.
---

# Nouveau projet : Claude → GitHub → Railway

Ce skill met en place une chaîne complète : le code est écrit dans Claude, poussé sur GitHub par PR, et Railway redéploie automatiquement la branche `main`. Il s'exécute **une fois par projet**. Les règles d'itération ultérieures sont écrites dans le `CLAUDE.md` du projet ; elles s'appliquent ensuite sans relancer le skill.

## Principes (pourquoi le skill est construit ainsi)

- **Une étape, une vérification, puis on avance.** Chaque étape se termine par un contrôle dont le résultat est montré à l'utilisateur. En cas d'échec : s'arrêter, expliquer en une phrase ce qui bloque et ce qu'il faut faire. Ne pas contourner un échec pour « finir quand même » : un projet à moitié branché (dépôt sans code, service jamais déployé) est pire qu'un arrêt net.
- **Confirmation avant toute création externe** : dépôt GitHub, projet Railway, base de données, domaine. Ces actions sont visibles, parfois facturées, et pénibles à défaire. Regrouper la confirmation (une seule question par étape), ne pas la répéter pour chaque appel.
- **Reprise sans doublon.** Avant de créer quoi que ce soit, vérifier si cela existe déjà. Si le dépôt ou le projet Railway existe, proposer de reprendre à l'étape suivante plutôt que de recréer.
- **Les contrôles mécaniques sont faits par les scripts** (`scripts/verify.sh`, `scripts/scaffold.mjs`), pas par l'appréciation du modèle. Leur code de sortie fait foi.
- **Aucun secret ne transite par le chat ni par le dépôt.** Les valeurs sont saisies par l'utilisateur dans l'interface Railway ; le skill vérifie leur présence par leur nom, sans lire ni afficher les valeurs.

Les chemins `scripts/` et `assets/` ci-dessous sont relatifs au dossier de ce skill.

## Étape 0 — Contrôle préalable

1. GitHub : `get_me` (outil GitHub MCP) → noter le login.
2. Railway : `whoami` puis `list-projects` (outils Railway MCP).
3. Si l'un des deux ne répond pas : s'arrêter et indiquer quel connecteur reconnecter (GitHub : https://claude.ai/connect-github ; Railway : connecteur Railway dans les réglages claude.ai).

Vérification : les deux comptes répondent. Afficher « GitHub : <login> · Railway : <compte> ».

## Étape 1 — Questions d'usage et profil

Poser ces 4 questions en une seule fois (outil `AskUserQuestion` s'il est disponible), puis demander le **nom du projet** (minuscules, chiffres, tirets) s'il n'est pas déjà donné :

1. **À quoi sert le projet ?** Site vitrine ou éditorial · Outil ou application (formulaires, comptes, tableau de bord) · Service sans interface (API, automatisation)
2. **Faut-il conserver des données ?** Non · Oui (formulaires enregistrés, utilisateurs, contenus)
3. **Le projet appelle-t-il une IA ou une API payante ?** Non · Oui
4. **Pour qui ?** Vous · Un client (domaine personnalisé)

Déduire le profil :

| Réponses | Profil | Options |
|---|---|---|
| Vitrine/éditorial, pas de données, pas d'IA | `astro` | — |
| Vitrine avec données ou IA | `nextjs` | `--db` et/ou `--ia` |
| Outil ou application | `nextjs` | `--db` si données, `--ia` si IA |
| Service sans interface | **non couvert** | Le dire : ce profil (FastAPI) n'est pas encore modélisé. Proposer `nextjs` avec routes `/api`, ou de s'arrêter. |

Projet client → option `--client`. Le nom du dépôt suit alors la forme `client-<nom>` sauf refus de l'utilisateur.

Présenter le résultat sous cette forme, puis **attendre la validation** (l'utilisateur peut forcer un autre profil) :

```
Projet : <nom> (dépôt privé LePrompteur/<nom>)
Profil : Next.js — options : base Postgres, clé IA
Pourquoi : outil avec formulaires enregistrés et appel à Claude côté serveur.
Créations prévues : dépôt GitHub privé, projet Railway <nom>, service web, base Postgres.
```

Vérification : nom libre côté GitHub (`search_repositories` avec `repo:<owner>/<nom>`, ou `get_file_contents` qui renvoie 404) et côté Railway (absent de `list-projects`). S'il existe déjà : proposer la reprise (voir « Reprise »).

## Étape 2 — Dépôt GitHub

Lire `references/github.md` avant cette étape (accès de session, limites connues).

1. `create_repository` : `name=<nom>`, `private=true`, `autoInit=true` (un premier commit sur `main` est nécessaire pour ouvrir une PR ensuite).
2. Rattacher le dépôt à la session : `add_repo` avec `access: "push"`, exécuter la commande de clonage qu'il renvoie, puis `register_repo_root`.
3. Créer une branche de travail : `git checkout -b init/ossature`.

Vérification : `git push --dry-run -u origin init/ossature` réussit. En cas de refus, voir `references/github.md` (installation de l'application GitHub Claude).

## Étape 3 — Ossature

Depuis la racine du clone :

```bash
node <skill>/scripts/scaffold.mjs --profil <astro|nextjs> --nom <nom> --dest . \
  --usage "<réponse à la question 1>" [--db] [--ia] [--client]
npm install --no-audit --no-fund      # crée package-lock.json, requis par Railway et la CI
bash scripts/verify.sh tout .
```

Le script vérifie tout avant d'écrire : si un fichier cible existe déjà, il n'écrit rien et liste les conflits. Seul le README créé par GitHub à l'initialisation est remplacé d'office. Un conflit signifie que le dépôt contient déjà du code : passer en « Reprise » plutôt que de forcer.

Ce que contient l'ossature : application minimale avec route de santé (`/health.json` ou `/api/health`), `railway.json` (healthcheck, redémarrage sur échec), CI GitHub (secrets, build, absence de clé dans le code navigateur), Dependabot, `.gitignore`, `.env.example` (noms seuls), `CLAUDE.md` avec les règles d'itération, et `scripts/verify.sh` copié dans le projet.

Vérification : `verify.sh tout` affiche 4 lignes `OK` (fichiers, secrets, build, bundle). Sinon, corriger avant tout commit.

## Étape 4 — Première PR

```bash
git add -A && git commit -m "Ossature <profil> générée par nouveau-projet"
git push -u origin init/ossature
```

Puis `create_pull_request` (base `main`, tête `init/ossature`) avec un corps qui liste le profil, les options et les vérifications passées. S'abonner à la PR (`subscribe_pr_activity`) pour suivre la CI.

Vérification : CI verte sur la PR. Ensuite **demander à l'utilisateur de fusionner** (ou de confirmer explicitement que Claude fusionne avec `merge_pull_request`). Railway ne déploie que `main` : tant que la PR n'est pas fusionnée, ne pas passer à l'étape 5, sinon le premier déploiement échoue sur une branche vide.

## Étape 5 — Railway

Lire `references/railway.md` avant cette étape (ordre des appels, raisons). Résumé :

1. `create-project` : `name=<nom>`, `defaultEnvironmentName="production"`. Demander si l'utilisateur veut les aperçus de PR (`prDeploys`), en précisant qu'ils créent un environnement temporaire facturé à l'usage par PR ouverte ; par défaut : non.
2. Si `--db` : `deploy-template` avec `code="postgres"`.
3. `create-service` **vide** nommé `web`.
4. `update-service` : région Europe `{"europe-west4-drams3a": {"numReplicas": 1}}`.
5. Variables (avant la source, pour que le premier build les ait) :
   - `--db` : `set-variables` `DATABASE_URL = ${{Postgres.DATABASE_URL}}` avec `skipDeploys: true` (référence, pas un secret).
   - `--ia` : demander à l'utilisateur de saisir `ANTHROPIC_API_KEY` dans Railway (service `web` → Variables). Ne jamais demander la valeur dans le chat.
6. `connect-service-source` : `repo=<owner>/<nom>`, `branch="main"`. Le build démarre.
7. `generate-domain` (sans `domain`) → adresse `*.up.railway.app`.
8. Si `--client` : `generate-domain` avec le domaine du client, puis transmettre les enregistrements DNS renvoyés.

Vérification : `describe-service` montre la source `<owner>/<nom>` sur `main`, la région Europe, et les noms de variables attendus (`DATABASE_URL`, `ANTHROPIC_API_KEY` selon les options). Vérifier les noms uniquement.

## Étape 6 — Premier déploiement

1. `list-deployments` (service `web`) jusqu'à un statut final. Le build prend en général 1 à 4 minutes ; entre deux vérifications, lire `get-logs` avec `types: ["build"]` pour suivre l'avancement.
2. Statut `FAILED` ou `CRASHED` : lire `get-logs` (`build` puis `deploy`), diagnostiquer, corriger par une PR. Ne pas relancer à l'aveugle.
3. Statut `SUCCESS` : `bash scripts/verify.sh http https://<domaine><route de santé>`.
   - Si la session ne peut pas joindre le domaine (codes 000/403 partout), se fier au statut `SUCCESS` (le healthcheck Railway a déjà validé la route) et à `get-logs` `types: ["http"]`.
   - Avec `--db`, une réponse 503 signifie que la base est injoignable : vérifier `DATABASE_URL`.

Vérification : statut `SUCCESS` et route de santé à 200.

## Étape 7 — Bilan

Terminer par ce bilan, sans autre commentaire :

```
## <nom> — en ligne
| Élément | État |
|---|---|
| Dépôt | LePrompteur/<nom> (privé) |
| PR initiale | <lien> — fusionnée |
| CI | verte |
| Railway | projet <nom> · service web · Europe |
| Site | https://<domaine> — santé 200 |
| Options | <liste> |

À faire de votre côté :
- <uniquement les réglages manuels restants, ex. protection de main, DNS client, clé IA>
```

## Reprise

Si l'étape 1 trouve un dépôt ou un projet Railway existant à ce nom, déterminer l'état réel avant toute action :
- Dépôt sans `railway.json` ni `package.json` → reprendre à l'étape 3.
- PR `init/ossature` ouverte → reprendre à l'étape 4 (CI, fusion).
- Projet Railway sans service `web`, ou service sans source, ou sans déploiement → reprendre à l'étape 5 au premier point manquant.
- Dernier déploiement en échec → étape 6, diagnostic.

Annoncer en une ligne l'étape de reprise et ce qui est déjà en place.

## Limites

- Profils couverts : `astro` (statique) et `nextjs`. Le profil API sans interface (FastAPI) n'est pas modélisé.
- Les versions des dépendances sont figées dans `assets/` et `scripts/scaffold.mjs` (testées le 2026-10-13) ; Dependabot les fait évoluer ensuite par PR.
- Pour écrire du code qui appelle Claude dans le projet (option `--ia`), s'appuyer sur le skill `claude-api` s'il est disponible.
