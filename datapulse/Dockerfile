# VITHI / DataPulse frontend — build static assets, serve with nginx
# Build from repo root:
#   docker build -t etl-obs-ui -f datapulse/Dockerfile datapulse
# Or via docker-compose.prod.yml (recommended)

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
# Relative API paths; nginx proxies /api /v1 /health to the api service
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
