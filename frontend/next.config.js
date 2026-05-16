const normalizeApiBase = (base) => {
  if (!base) return 'https://study-hub.store/api';
  const trimmed = base.replace(/\/+$/, '');
  if (/\/api$/i.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}/api`;
};

const rawBase = process.env.NEXT_PUBLIC_API_BASE || process.env.API_BASE_URL;
const apiBase = rawBase ? normalizeApiBase(rawBase) : undefined;
if (apiBase) {
  process.env.NEXT_PUBLIC_API_BASE = apiBase;
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    ...(apiBase ? { NEXT_PUBLIC_API_BASE: apiBase } : {}),
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },
};

module.exports = nextConfig;
