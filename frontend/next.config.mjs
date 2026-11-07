/** Configuración Next.js: proxy /api/* hacia el backend del VPS.
 *
 * HACHE_API_ORIGIN: origen del backend (ej: https://api.midominio.com).
 * Nunca hay IPs fijas en el código: todo va por variables de entorno.
 */
const backend = process.env.HACHE_API_ORIGIN || "http://127.0.0.1:8900";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
