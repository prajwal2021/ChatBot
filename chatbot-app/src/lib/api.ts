/**
 * Base URL for the FastAPI backend (vectors/).
 *
 * Baked into the client bundle at build time from NEXT_PUBLIC_API_URL, so it
 * must be passed as a build ARG — setting it only at container runtime has no
 * effect on an already-built bundle.
 *
 * Deployed behind nginx the backend is a sibling subpath of the app's basePath
 * (`/chatbot` → `/chatbot-api`), so the fallback here is a relative same-origin
 * path rather than a host. There is deliberately no `http://localhost:8000`
 * fallback: that silently produces a bundle that works on a dev machine and is
 * broken for every real user, with no build-time error to catch it.
 *
 * These URLs address the backend directly and are NOT affected by Next's
 * basePath — do not prefix them with `/chatbot`.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/chatbot-api";
