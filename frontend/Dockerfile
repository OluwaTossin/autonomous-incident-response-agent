# Static Next.js export served by nginx (product Compose default UI).
# Build-time API URL is baked into the bundle — use host-reachable URL (see docker-compose.yml).
FROM node:20-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:18080
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/out /usr/share/nginx/html
COPY nginx.default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
