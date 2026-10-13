# GitHub — accès, limites et réglages manuels

## Accès de la session
- Une session Claude Code cloud ne voit que les dépôts choisis à son ouverture. Un dépôt créé en cours de session doit être rattaché avec `add_repo` (`access: "push"`), puis cloné avec la commande renvoyée, puis déclaré avec `register_repo_root`.
- Si `add_repo` ou le push est refusé : l'application GitHub Claude n'a probablement pas accès au nouveau dépôt. Remède : https://github.com/apps/claude/installations/select_target → choisir le compte → « All repositories » (recommandé, évite la manipulation à chaque projet) ou ajouter le dépôt. Puis réessayer une fois.
- Si le rattachement reste impossible : s'arrêter et proposer d'ouvrir une nouvelle session avec le dépôt sélectionné ; la reprise se fera à l'étape 3.

## Fichiers de workflow
Pousser `.github/workflows/ci.yml` exige la permission « workflows » côté application GitHub. Si le push est refusé pour ce seul fichier : le retirer du commit (`git rm --cached .github/workflows/ci.yml`), pousser le reste, et signaler dans le bilan que la CI est à ajouter manuellement (copier le fichier depuis la PR). Ne pas désactiver d'autres contrôles pour compenser.

## Protection de la branche `main`
- Les outils GitHub disponibles ne permettent pas de configurer la protection de branche : c'est un réglage manuel.
- Sur GitHub Free, la protection de branche et les rulesets ne s'appliquent **pas aux dépôts privés** (ils exigent GitHub Pro, Team ou Enterprise). Avec un compte gratuit et un dépôt privé, la règle « `main` n'avance que par PR » repose sur le `CLAUDE.md` du projet et sur la discipline de fusion. Le dire dans le bilan plutôt que de laisser croire à une protection technique.
- Avec un plan qui le permet : Settings → Branches (ou Rules) → protéger `main`, exiger une PR et le passage du check `CI / verifier`. Lien direct : `https://github.com/<owner>/<nom>/settings/branches`.

## Fusion
Ne fusionner la PR qu'avec l'accord explicite de l'utilisateur, une fois la CI verte. Par défaut, c'est l'utilisateur qui fusionne.
