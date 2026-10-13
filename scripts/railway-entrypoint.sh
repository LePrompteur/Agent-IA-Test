#!/usr/bin/env bash
# Exécution de l'agent sur Railway : une exécution par déploiement (ou par déclenchement cron).
#   1. Méta-tests déterministes (sans API) : valident l'image (Chromium, outils, garde-fous).
#   2. Si ANTHROPIC_API_KEY est défini : lance l'agent avec AGENT_ARGS.
set -euo pipefail

AGENT_ARGS="${AGENT_ARGS:---run-all --filter eval}"

echo "▶ Méta-tests de l'image"
python -m pytest tests/evals -q -m "not live"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ℹ ANTHROPIC_API_KEY non défini : agent non lancé. Ajoutez la variable dans Railway puis redéployez."
  exit 0
fi

echo "▶ python src/main.py ${AGENT_ARGS}"
# shellcheck disable=SC2086
exec python src/main.py ${AGENT_ARGS}
