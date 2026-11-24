import type { NextConfig } from "next";

// On the server the app lives under a sub-path (e.g. /kb-curation) behind nginx.
// The value must be the same at build time and at `next start`, so the Docker
// image sets it in both stages. Leave unset for local development.
const basePath = process.env.NEXT_BASE_PATH || undefined;

const nextConfig: NextConfig = {
  basePath,
  // the browser needs the sub-path too, to send signed-out users to /login
  env: { NEXT_PUBLIC_BASE_PATH: basePath ?? "" },
  // Previous architecture, hidden for now: its pages send you to ServiceNow. Drop a name from the list to bring a page back.
  async redirects() {
    const bot = ":bot((?!login$)[^/.]+)"; // a chatbot key: never /login, never a file like favicon.ico
    return [
      { source: `/${bot}`, destination: "/:bot/servicenow", permanent: false },
      { source: `/${bot}/:old(sources|pages|changes|scope|review|publish|kb|document)`, destination: "/:bot/servicenow", permanent: false },
    ];
  },
};

export default nextConfig;
