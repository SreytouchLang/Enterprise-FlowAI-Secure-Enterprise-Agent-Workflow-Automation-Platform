FROM node:22-alpine AS dependencies
WORKDIR /srv/web
COPY apps/web/package*.json ./
RUN npm ci
FROM node:22-alpine AS builder
WORKDIR /srv/web
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /srv/web/node_modules ./node_modules
COPY apps/web ./
RUN mkdir -p public && npm run build
FROM node:22-alpine AS runner
WORKDIR /srv/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /srv/web/public ./public
COPY --from=builder --chown=node:node /srv/web/.next/standalone ./
COPY --from=builder --chown=node:node /srv/web/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
