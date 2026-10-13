-- Migration initiale : valide la chaîne GitHub → Postgres (Railway).
-- Les migrations suivantes ajoutent un fichier horodaté dans ce dossier :
--   supabase migration new <nom>   (ou créer YYYYMMDDHHMMSS_<nom>.sql à la main)
create schema if not exists app;
comment on schema app is 'Schéma applicatif du projet agent-ia-test';
