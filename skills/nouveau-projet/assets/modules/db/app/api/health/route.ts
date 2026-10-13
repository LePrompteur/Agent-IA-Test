import { getPool } from "@/lib/db";

// Vérifiée par Railway (healthcheckPath) et par scripts/verify.sh.
// Répond 503 si la base est injoignable, sans exposer le détail de l'erreur.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await getPool().query("select 1");
    return Response.json({ status: "ok", db: "ok" });
  } catch {
    return Response.json({ status: "erreur", db: "injoignable" }, { status: 503 });
  }
}
