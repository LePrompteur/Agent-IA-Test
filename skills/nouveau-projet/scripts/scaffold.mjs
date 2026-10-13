#!/usr/bin/env node
// Génère l'ossature d'un projet à partir des modèles du skill.
// Usage :
//   node scaffold.mjs --profil astro|nextjs --nom <nom> --dest <dossier>
//                     --usage "<texte>" [--db] [--ia] [--client]
// Déterministe : mêmes paramètres, mêmes fichiers. N'écrit rien si un fichier cible existe déjà
// (seul le README d'initialisation GitHub peut être remplacé).
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const SKILL = join(dirname(fileURLToPath(import.meta.url)), "..");
const ASSETS = join(SKILL, "assets");

// Versions exactes des dépendances ajoutées par les modules (mises à jour ensuite par Dependabot).
const MODULE_DEPS = {
  db: { dependencies: { pg: "8.23.1", "server-only": "0.0.1" }, devDependencies: { "@types/pg": "8.23.1" } },
  ia: { dependencies: { "@anthropic-ai/sdk": "0.133.0", "server-only": "0.0.1" }, devDependencies: {} },
};
const MODULE_ENV = {
  db: "# Fournie par Railway : ${{Postgres.DATABASE_URL}}\nDATABASE_URL=",
  ia: "# À saisir dans Railway (Variables du service web), jamais dans le code\nANTHROPIC_API_KEY=",
};

function parseArgs(argv) {
  const out = { db: false, ia: false, client: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--db" || a === "--ia" || a === "--client") out[a.slice(2)] = true;
    else if (a.startsWith("--")) out[a.slice(2)] = argv[++i];
  }
  return out;
}

function fail(msg) {
  console.error(`ÉCHEC ${msg}`);
  process.exit(1);
}

const args = parseArgs(process.argv.slice(2));
if (!["astro", "nextjs"].includes(args.profil)) fail("--profil doit valoir astro ou nextjs");
if (!args.nom || !/^[a-z0-9][a-z0-9-]{1,62}$/.test(args.nom)) fail("--nom : minuscules, chiffres et tirets uniquement");
if (!args.dest) fail("--dest manquant");
if (!args.usage) fail("--usage manquant");
if (args.profil === "astro" && (args.db || args.ia)) {
  fail("le profil astro est statique : les options --db et --ia imposent le profil nextjs");
}

const modules = [args.db && "db", args.ia && "ia"].filter(Boolean);
const techno = args.profil === "astro" ? "Astro (site statique)" : "Next.js (TypeScript, serveur Node)";
const health = args.profil === "astro" ? "/health.json" : "/api/health";
const options = [
  args.db && "base Postgres",
  args.ia && "clé d'API IA (côté serveur)",
  args.client && "projet client (domaine personnalisé)",
].filter(Boolean);

const vars = {
  "{{NOM}}": args.nom,
  "{{USAGE}}": args.usage,
  "{{TECHNO}}": techno,
  "{{HEALTH}}": health,
  "{{OPTIONS}}": options.length ? options.join(", ") : "aucune",
  "{{DATE}}": new Date().toISOString().slice(0, 10),
};

const written = [];

function render(text) {
  let out = text;
  for (const [k, v] of Object.entries(vars)) out = out.split(k).join(v);
  return out;
}

// Plan complet (source → cible) établi avant toute écriture : un conflit arrête tout
// sans laisser de projet à moitié généré.
function planTree(src, dest, plan) {
  for (const entry of readdirSync(src)) {
    const from = join(src, entry);
    // Un modèle ne peut pas s'appeler .gitignore (ignoré à l'empaquetage) : renommage ici.
    const to = join(dest, entry === "gitignore" ? ".gitignore" : entry);
    if (statSync(from).isDirectory()) planTree(from, to, plan);
    else plan.set(to, from); // les modules, ajoutés en dernier, remplacent les fichiers du profil
  }
  return plan;
}

// Le README créé par GitHub (autoInit) se limite au titre et à la description : il peut être remplacé.
function isGithubInitReadme(path) {
  return path === join(args.dest, "README.md") && readFileSync(path, "utf8").trim().split("\n").length <= 3;
}

const plan = new Map();
planTree(join(ASSETS, "commun"), args.dest, plan);
planTree(join(ASSETS, args.profil), args.dest, plan);
for (const m of modules) planTree(join(ASSETS, "modules", m), args.dest, plan);
const extra = [join(args.dest, ".env.example"), join(args.dest, "scripts", "verify.sh")];

const conflicts = [...plan.keys(), ...extra].filter((to) => existsSync(to) && !isGithubInitReadme(to));
if (conflicts.length) {
  fail(`fichiers déjà présents, rien n'a été écrit :\n   ${conflicts.map((c) => relative(args.dest, c)).join("\n   ")}`);
}

for (const [to, from] of plan) {
  mkdirSync(dirname(to), { recursive: true });
  writeFileSync(to, render(readFileSync(from, "utf8")));
  written.push(relative(args.dest, to));
}

// Dépendances des modules
const pkgPath = join(args.dest, "package.json");
const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
for (const m of modules) {
  Object.assign((pkg.dependencies ??= {}), MODULE_DEPS[m].dependencies);
  Object.assign((pkg.devDependencies ??= {}), MODULE_DEPS[m].devDependencies);
}
writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");

// .env.example : noms de variables uniquement
const envLines = ["# Copier en .env pour le développement local. Ne jamais versionner .env."];
for (const m of modules) envLines.push("", MODULE_ENV[m]);
writeFileSync(join(args.dest, ".env.example"), envLines.join("\n") + "\n");
written.push(".env.example");

// Le script de vérification voyage avec le projet (utilisé par la CI)
mkdirSync(join(args.dest, "scripts"), { recursive: true });
cpSync(join(SKILL, "scripts", "verify.sh"), join(args.dest, "scripts", "verify.sh"));
written.push("scripts/verify.sh");

console.log(`OK ossature ${args.profil}${modules.length ? " + " + modules.join(" + ") : ""} dans ${args.dest}`);
for (const f of written.sort()) console.log(`   ${f}`);
