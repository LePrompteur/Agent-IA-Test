# {{NOM}}

## Profil
- Usage : {{USAGE}}
- Technologie : {{TECHNO}}
- Options : {{OPTIONS}}
- Créé le {{DATE}} avec le skill `nouveau-projet`. Ce choix a été validé par le propriétaire : ne pas changer de technologie sans demande explicite.

## Chaîne de déploiement
Code (Claude) → PR GitHub → CI verte → fusion dans `main` par le propriétaire → Railway redéploie `main` automatiquement.
- Railway : projet `{{NOM}}`, service `web`, environnement `production`.
- Santé : `{{HEALTH}}` doit répondre 200.

## Règles d'itération
- Travailler sur une branche dédiée, jamais directement sur `main`.
- Fin d'itération : commit, push, puis création ou mise à jour de la PR vers `main`. Une PR par chantier, mise à jour à chaque push.
- Avant chaque push : `npm run build` et `bash scripts/verify.sh secrets .` doivent passer.
- Ne pas fusionner soi-même : la fusion revient au propriétaire.
- Après une fusion : vérifier le déploiement Railway (statut SUCCESS, `{{HEALTH}}` en 200).

## Secrets
- Aucun secret dans le dépôt ni dans le chat. `.env.example` ne contient que des noms de variables.
- Les valeurs sont saisies par le propriétaire dans l'interface Railway (Variables du service `web`).
- Les clés d'API ne sont lues que côté serveur ; `bash scripts/verify.sh bundle .` vérifie qu'aucune ne fuit dans le code envoyé au navigateur.

## Commandes
- Développement : `npm run dev`
- Build : `npm run build`
- Vérifications : `bash scripts/verify.sh tout .`
