import type { NextConfig } from "next";

// On the server the app lives under a sub-path (e.g. /kb-curation) behind nginx.
// The value must be the same at build time and at `next start`, so the Docker
// image sets it in both stages. Leave unset for local development.
const basePath = process.env.NEXT_BASE_PATH || undefined;

const nextConfig: NextConfig = {
  basePath,
};

export default nextConfig;
