import "server-only";
import Anthropic from "@anthropic-ai/sdk";

// Client Claude, utilisable uniquement côté serveur (routes /api, Server Actions).
// "server-only" fait échouer le build si ce fichier est importé dans un composant client.
// La clé est saisie dans Railway (variable ANTHROPIC_API_KEY), jamais dans le code.
let client: Anthropic | undefined;

export function getClaude(): Anthropic {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY manquante");
  }
  client ??= new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  return client;
}
