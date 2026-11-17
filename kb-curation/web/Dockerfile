FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Baked into the client bundle at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8030
ARG NEXT_BASE_PATH=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_BASE_PATH=$NEXT_BASE_PATH NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ARG NEXT_BASE_PATH=
# next start re-reads next.config.ts, so the base path must match the build.
ENV NODE_ENV=production NEXT_BASE_PATH=$NEXT_BASE_PATH NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
