#!/usr/bin/env bash
# Contrôles mécaniques du skill nouveau-projet. Code de sortie ≠ 0 = arrêt.
# Usage :
#   verify.sh fichiers <dossier>   fichiers attendus présents, .env absent du suivi git
#   verify.sh secrets  <dossier>   aucun secret en clair dans les fichiers versionnables
#   verify.sh build    <dossier>   npm ci + npm run build
#   verify.sh bundle   <dossier>   aucune clé serveur dans le code envoyé au navigateur
#   verify.sh http     <url>       la route répond 200 (réessaie pendant ~3 min)
#   verify.sh tout     <dossier>   fichiers + secrets + build + bundle
set -uo pipefail

ok()    { echo "OK     $*"; }
echec() { echo "ÉCHEC  $*"; exit 1; }

profil_de() {
  if [ -f "$1/astro.config.js" ]; then echo astro
  elif [ -f "$1/next.config.mjs" ]; then echo nextjs
  else echo inconnu; fi
}

cmd_fichiers() {
  local d="$1" p; p=$(profil_de "$d")
  [ "$p" = inconnu ] && echec "profil non reconnu (ni astro.config.js ni next.config.mjs)"
  local requis=(package.json package-lock.json railway.json CLAUDE.md README.md .gitignore .env.example \
                scripts/verify.sh .github/workflows/ci.yml .github/dependabot.yml)
  if [ "$p" = astro ]; then requis+=(astro.config.js public/health.json src/pages/index.astro)
  else requis+=(next.config.mjs tsconfig.json app/layout.tsx app/page.tsx app/api/health/route.ts); fi
  local manquants=()
  for f in "${requis[@]}"; do [ -e "$d/$f" ] || manquants+=("$f"); done
  [ ${#manquants[@]} -eq 0 ] || echec "fichiers manquants : ${manquants[*]}"
  grep -qxF ".env" "$d/.gitignore" || echec ".env n'est pas ignoré par .gitignore"
  if git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local suivis; suivis=$(git -C "$d" ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$' || true)
    [ -z "$suivis" ] || echec "fichier .env suivi par git : $suivis"
  fi
  grep -qE '^[A-Z_]+=.+' "$d/.env.example" && echec ".env.example contient une valeur : il ne doit lister que des noms"
  ok "fichiers ($p)"
}

cmd_secrets() {
  local d="$1"
  # Motifs de secrets courants : clés Anthropic/OpenAI, jetons GitHub/Slack/Railway, clés AWS,
  # clés privées, URL de base de données avec mot de passe.
  local motif='sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(postgres|postgresql|mysql|mongodb|redis)(\+srv)?://[^:/@[:space:]]+:[^@[:space:]$]+@'
  local trouves
  trouves=$(grep -rInE "$motif" "$d" \
      --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.next --exclude-dir=dist \
      --exclude-dir=.astro --exclude=package-lock.json --exclude=verify.sh 2>/dev/null \
    | cut -c1-160 || true)
  [ -z "$trouves" ] || echec "secret probable :"$'\n'"$trouves"
  ok "aucun secret détecté"
}

cmd_build() {
  local d="$1"
  (cd "$d" && npm ci --no-audit --no-fund >/dev/null 2>&1) || echec "npm ci"
  (cd "$d" && npm run build >/tmp/verify-build.log 2>&1) || { tail -30 /tmp/verify-build.log; echec "npm run build"; }
  ok "build"
}

cmd_bundle() {
  local d="$1" cible
  case "$(profil_de "$d")" in
    astro)  cible="$d/dist" ;;
    nextjs) cible="$d/.next/static" ;;
    *) echec "profil non reconnu" ;;
  esac
  [ -d "$cible" ] || echec "lancer le build avant ce contrôle ($cible absent)"
  # Le nom d'une variable serveur dans le code navigateur signale un import côté client.
  local fuites; fuites=$(grep -rlE 'ANTHROPIC_API_KEY|DATABASE_URL|sk-ant-' "$cible" 2>/dev/null || true)
  [ -z "$fuites" ] || echec "variable serveur présente dans le code navigateur : $fuites"
  ok "code navigateur sans variable serveur"
}

cmd_http() {
  local url="$1" code
  for i in $(seq 1 18); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || echo 000)
    [ "$code" = 200 ] && { ok "$url → 200"; return 0; }
    echo "...    $url → $code (essai $i/18)"
    [ "$i" -lt 18 ] && sleep 10
  done
  echec "$url ne répond pas 200 (dernier code : $code). Si le code est 000 ou 403 partout, le réseau de la session bloque peut-être le domaine : se fier au statut Railway et aux logs http."
}

[ $# -eq 2 ] || { sed -n 2,9p "$0"; exit 2; }
case "$1" in
  fichiers) cmd_fichiers "$2" ;;
  secrets)  cmd_secrets "$2" ;;
  build)    cmd_build "$2" ;;
  bundle)   cmd_bundle "$2" ;;
  http)     cmd_http "$2" ;;
  tout)     cmd_fichiers "$2" && cmd_secrets "$2" && cmd_build "$2" && cmd_bundle "$2" ;;
  *) sed -n 2,9p "$0"; exit 2 ;;
esac
