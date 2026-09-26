# Prod webapp: SvelteKit static build → nginx.
# Build context: repository root.

FROM node:22-alpine AS build

WORKDIR /app

COPY webapp/package.json webapp/package-lock.json* ./
RUN npm ci || npm install

COPY webapp/ ./

# PUBLIC_* baked at build time (SvelteKit)
ARG PUBLIC_API_BASE=/api
ENV PUBLIC_API_BASE=${PUBLIC_API_BASE}

RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/webapp/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
