ARG NODE_IMAGE=node:24-bookworm-slim
ARG NGINX_IMAGE=nginx:stable-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --ignore-scripts --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
