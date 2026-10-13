# Railway — ordre des appels et raisons

## Comment Railway construit le projet
- Builder **Railpack** (par défaut), configuré par `railway.json` dans le dépôt (healthcheck, politique de redémarrage).
- **Astro** : détecté via `astro.config.js` avec une sortie statique ; Railpack sert `dist/` sans configuration (mode « static site »). Ne pas renommer le fichier en `.mjs` ni passer en `output: "server"` sans revoir le déploiement.
- **Next.js** : `npm run build` puis `npm start` (`next start`), qui écoute sur la variable `PORT` fournie par Railway. Ne pas ajouter `output: "export"`, qui supprimerait les routes `/api`.
- `package-lock.json` doit être versionné : Railpack installe avec `npm ci`.

## Ordre des appels (et pourquoi)
1. `create-project` (`defaultEnvironmentName: "production"`) → noter `projectId` et l'`environmentId` de production (`list-services`).
2. `--db` : `deploy-template` `code: "postgres"`. Le mot de passe est généré par Railway ; ne jamais en fournir. Le service s'appelle `Postgres`.
3. `create-service` **sans image** nommé `web`. Pourquoi vide : `create-deployment` lancerait un build immédiat, avant que les variables existent ; avec `--db`, ce premier build échouerait au healthcheck (503) et laisserait un déploiement en échec dans l'historique.
4. `update-service` : `regions: {"europe-west4-drams3a": {"numReplicas": 1}}` (Europe, proche des utilisateurs français). Si la région est refusée, garder celle par défaut et le signaler.
5. Variables :
   - `--db` : `set-variables` `{"DATABASE_URL": "${{Postgres.DATABASE_URL}}"}`, `skipDeploys: true`. C'est une référence résolue par Railway, pas un secret en clair.
   - `--ia` : l'utilisateur saisit `ANTHROPIC_API_KEY` dans l'interface (projet → service `web` → Variables). Attendre sa confirmation, puis vérifier la présence du **nom** via `describe-service` (`variableNames`). Ne pas utiliser `list-variables`, qui peut renvoyer les valeurs en clair.
6. `connect-service-source` : `repo: "<owner>/<nom>"`, `branch: "main"`. Déclenche le premier build.
7. `generate-domain` sans `domain` → `*.up.railway.app`.
8. `--client` : `generate-domain` avec `domain`, puis transmettre les enregistrements DNS. La vérification DNS peut prendre de quelques minutes à quelques heures : `domain-status` pour suivre, sans bloquer le bilan.

## Modifications en attente (« staged »)
Si `describe-service` montre un bloc `staged` non vide, des modifications attendent d'être appliquées. Ne pas les appliquer (`accept-deploy`) sans les montrer à l'utilisateur et obtenir son accord.

## Diagnostic d'un échec
- `get-logs` `types: ["build"]` : dépendances, erreurs de compilation.
- `get-logs` `types: ["deploy"]` : crash au démarrage, port, variable manquante.
- Healthcheck en échec : la route de santé ne répond pas 200 dans le délai (60 s) ; avec `--db`, vérifier `DATABASE_URL`.
- Corriger par une PR sur le dépôt, jamais par une modification manuelle non tracée.
