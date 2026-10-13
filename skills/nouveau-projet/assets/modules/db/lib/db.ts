import "server-only";
import { Pool } from "pg";

// DATABASE_URL est fournie par Railway : ${{Postgres.DATABASE_URL}}.
let pool: Pool | undefined;

export function getPool(): Pool {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL manquante");
  }
  pool ??= new Pool({ connectionString: process.env.DATABASE_URL, max: 5 });
  return pool;
}
