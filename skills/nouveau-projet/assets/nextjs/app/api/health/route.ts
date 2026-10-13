// Vérifiée par Railway (healthcheckPath) et par scripts/verify.sh.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
