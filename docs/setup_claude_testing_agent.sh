#!/usr/bin/env bash
# ==============================================================================
# Script d'initialisation du projet : Agent de Test Autonome avec Claude Code
# ==============================================================================
# Ce script génère l'arborescence, les fichiers de configuration, le CLAUDE.md,
# le System Prompt et l'outillage de base (Playwright + Claude API Tool Use).

set -e

PROJECT_NAME="claude-testing-agent"

echo "🚀 Initialisation du projet $PROJECT_NAME..."

# 1. Création de la structure des dossiers
mkdir -p "$PROJECT_NAME"/{config,src/agent,src/tools,src/prompts,scenarios,tests/evals,reports}

cd "$PROJECT_NAME"

# 2. Fichier de mémoire projet CLAUDE.md (Spécifique à Claude Code)
cat << 'EOF' > CLAUDE.md
# Configuration Projet : Claude QA Testing Agent

## Description
Agent de test logiciel autonome basé sur Claude. Il exécute des scénarios de tests E2E, de résilience et d'API en s'appuyant sur l'arbre d'accessibilité (A11y) et Playwright.

## Directives d'architecture & Bonnes pratiques
- **Séparation des responsabilités** :
  - `src/agent/` : Raisonnement, boucle décisionnelle (Agent Loop), gestion du contexte.
  - `src/tools/` : Exécution mécanique (Playwright, capture DOM, logs réseau).
- **Assertion par intention** : Toujours évaluer les objectifs fonctionnels (A11y/rôle) plutôt que des sélecteurs CSS rigides.
- **Garde-fous** : Limite stricte de 15 itérations par test. Arrêt immédiat si 3 actions consécutives ne modifient pas l'état du DOM.

## Commandes de développement
- Executer un scénario : `python main.py --scenario scenarios/01_e2e_auth.json`
- Lancer la suite d'Evals (méta-tests) : `pytest tests/evals/`
- Nettoyer les rapports : `rm -rf reports/*`

## Format des Rapports
Tous les résultats de test doivent générer un fichier JSON et un résumé Markdown structuré dans `./reports/`.
EOF

# 3. System Prompt principal de l'agent
cat << 'EOF' > src/prompts/system_prompt.txt
Vous êtes un ingénieur QA expert et un Agent de Test Logiciel Autonome ("Claude QA Agent").
Votre rôle est d'exécuter et de valider des scénarios de test sur des applications web de manière autonome.

### RÈGLES DE COMPORTEMENT :
1. **Analyse d'intention** : Ne vous fiez pas uniquement aux sélecteurs CSS. Utilisez l'arbre d'accessibilité (A11y) pour interagir avec les éléments par leur rôle (bouton, champ, lien).
2. **Cycle de décision (Agent Loop)** :
   - Inspecter l'état actuel de la page via `capture_page_state`.
   - Analyser si l'objectif est atteint ou quelle action intermédiaire est requise.
   - Sélectionner et exécuter l'outil adéquat (`click_element`, `fill_input`, etc.).
   - Analyser le résultat (`tool_result`) et ajuster votre stratégie en cas d'erreur.
3. **Gestion des pannes** :
   - En cas d'erreur visuelle ou de blocage, interrogez systématiquement `get_console_logs` pour vérifier les erreurs réseau/JavaScript (4xx/5xx).
   - En cas d'overlay/popup (RGPD, modale), fermez-la avant de poursuivre le scénario principal.
4. **Assertions** : Ne validez un test que si l'état métier ET l'état réseau confirment le succès. Attention aux faux positifs visuels !
EOF

# 4. Configuration globale
cat << 'EOF' > config/config.json
{
  "max_iterations": 15,
  "timeout_seconds": 300,
  "headless": true,
  "viewport": {
    "width": 1280,
    "height": 720
  },
  "screenshot_on_failure": true
}
EOF

# 5. Définition des Schémas d'Outils (Tools Python)
cat << 'EOF' > src/tools/schemas.py
"""
Définition des schémas d'outils au format Claude Tool Use API.
"""

TOOLS = [
    {
        "name": "navigate_to_url",
        "description": "Charge une URL dans le navigateur et attend le chargement du DOM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "L'URL complète à charger."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "capture_page_state",
        "description": "Extrait l'arbre d'accessibilité (A11y) simplifié, l'URL actuelle et une capture d'écran.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "click_element",
        "description": "Effectue un clic sur un élément interactif identifié par son rôle ou sa description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "L'identifiant A11y ou le sélecteur cible."},
                "description": {"type": "string", "description": "Description fonctionnelle de l'action."}
            },
            "required": ["element_id"]
        }
    },
    {
        "name": "fill_input",
        "description": "Saisit du texte dans un champ de formulaire.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Identifiant du champ."},
                "value": {"type": "string", "description": "La valeur à saisir."}
            },
            "required": ["element_id", "value"]
        }
    },
    {
        "name": "get_console_logs",
        "description": "Récupère les logs console JavaScript et les requêtes HTTP en erreur (4xx/5xx).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "assert_condition",
        "description": "Évalue une condition fonctionnelle de succès ou d'échec.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expectation": {"type": "string", "description": "Attendu fonctionnel."},
                "status": {"type": "string", "enum": ["PASSED", "FAILED"], "description": "Résultat de l'assertion."},
                "reason": {"type": "string", "description": "Justification détaillée."}
            },
            "required": ["expectation", "status", "reason"]
        }
    }
]
EOF

# 6. Exemple de Scénario de Test JSON
cat << 'EOF' > scenarios/01_e2e_auth_nominal.json
{
  "id": "TC_E2E_001",
  "name": "Authentification Nominale Utilisateur",
  "target_url": "https://example.com/login",
  "objective": "Connecter un utilisateur existant avec identifiants valides et vérifier l'accès au Dashboard.",
  "steps": [
    "Naviguer vers l'URL de connexion.",
    "Remplir le champ e-mail avec 'user@test.com'.",
    "Remplir le champ mot de passe avec 'Password123!'.",
    "Cliquer sur le bouton 'Se connecter'.",
    "Vérifier la redirection vers /dashboard et la présence du message de bienvenue."
  ]
}
EOF

# 7. Script principal d'entrée (Main Agent Loop Skeleton)
cat << 'EOF' > main.py
import json
import argparse
from pathlib import Path

def load_config():
    with open("config/config.json") as f:
        return json.load(f)

def run_agent_scenario(scenario_path):
    print(f"🔄 Chargement du scénario : {scenario_path}")
    with open(scenario_path) as f:
        scenario = json.load(f)
    
    print(f"🎯 Objectif : {scenario['objective']}")
    print("🤖 Initialisation de l'Agent Loop Claude...")
    # Ici s'insère la boucle d'interaction avec l'API Anthropic / Claude Code
    print("✅ Structure prête. Intégrez votre clé ANTHROPIC_API_KEY et lancez le runner.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Runner de l'Agent de Test Claude")
    parser.add_argument("--scenario", required=True, help="Chemin vers le fichier JSON du scénario")
    args = parser.parse_args()
    
    run_agent_scenario(args.scenario)
EOF

# 8. Fichier de dépendances requirements.txt
cat << 'EOF' > requirements.txt
anthropic>=0.20.0
playwright>=1.40.0
pytest>=8.0.0
pydantic>=2.0.0
python-dotenv>=1.0.0
EOF

chmod +x main.py

echo "✅ Projet $PROJECT_NAME créé avec succès !"
echo "👉 Pour démarrer : cd $PROJECT_NAME && pip install -r requirements.txt && python -m playwright install"
