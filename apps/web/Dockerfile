# Multi-stage production Dockerfile for CHAOS-INTEL Web Dashboard
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci

# Copy source and build
COPY apps/web/ ./
RUN npm run build

# Stage 2: Production Nginx Server
FROM nginx:1.27-alpine

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]

