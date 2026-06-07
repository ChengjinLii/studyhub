const normalizeApiBase = (base) => {
  if (!base) return 'https://study-hub.store/api';
  const trimmed = base.replace(/\/+$/, '');
  if (/\/api$/i.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}/api`;
};

const extractOrigin = (value) => {
  try {
    return new URL(value).origin;
  } catch {
    return undefined;
  }
};

const rawBase = process.env.NEXT_PUBLIC_API_BASE || process.env.API_BASE_URL;
const apiBase = rawBase ? normalizeApiBase(rawBase) : undefined;
const apiOrigin = apiBase ? extractOrigin(apiBase) : undefined;
if (apiBase) {
  process.env.NEXT_PUBLIC_API_BASE = apiBase;
  if (apiOrigin) {
    process.env.NEXT_PUBLIC_API_ORIGIN = apiOrigin;
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  compress: true,
  poweredByHeader: false,
  reactStrictMode: true,
  env: {
    ...(apiBase
      ? {
          NEXT_PUBLIC_API_BASE: apiBase,
          ...(apiOrigin ? { NEXT_PUBLIC_API_ORIGIN: apiOrigin } : {}),
        }
      : {}),
  },
  async headers() {
    const immutableAssetHeaders = [
      {
        key: 'Cache-Control',
        value: 'public, max-age=31536000, immutable',
      },
    ];
    const staticAssetHeaders = [
      {
        key: 'Cache-Control',
        value: 'public, max-age=2592000, stale-while-revalidate=86400',
      },
    ];
    return [
      {
        source: '/_next/static/:path*',
        headers: immutableAssetHeaders,
      },
      {
        source: '/icons/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/local/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/wechat/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/payments/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/xmas/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/placeholders/:path*',
        headers: staticAssetHeaders,
      },
      {
        source: '/favicon.png',
        headers: staticAssetHeaders,
      },
      {
        source: '/manifest.json',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=3600, stale-while-revalidate=86400',
          },
        ],
      },
      {
        source: '/sw.js',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=0, must-revalidate',
          },
        ],
      },
    ];
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },
};

module.exports = nextConfig;
