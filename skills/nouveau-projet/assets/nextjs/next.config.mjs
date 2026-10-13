// Serveur Node (next start) : ne pas ajouter output: "export",
// sinon les routes serveur (/api/*) disparaissent.
/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
};

export default nextConfig;
