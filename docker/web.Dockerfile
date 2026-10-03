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
# Apply vendor patches missing from the upstream image; fail if patched versions
# are unavailable rather than publishing an image below the security baseline.
RUN --mount=type=secret,id=proxy_roots,required=false \
    if [ -f /run/secrets/proxy_roots ]; then export SSL_CERT_FILE=/run/secrets/proxy_roots; fi; \
    apk upgrade --no-cache \
    && apk add --no-cache "libexpat>=2.8.5-r0" "pcre2>=10.49-r0"
COPY --chmod=0644 docker/nginx.conf /etc/nginx/passit.conf.template
COPY --chmod=0755 docker/start-web.sh /usr/local/bin/passit-web
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["/bin/sh", "/usr/local/bin/passit-web"]
CMD ["-g", "daemon off;"]
