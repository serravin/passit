ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE} AS dependencies
WORKDIR /app
COPY pyproject.toml uv.lock ./
# The optional CA mount supports managed build proxies without retaining their CA
# or credentials in the image. Ordinary local builds use the image's normal trust.
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --only-binary=:all: --no-cache-dir uv==0.12.19
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    UV_LINK_MODE=copy uv sync --frozen --no-dev --no-install-project --no-build --no-managed-python

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 passit && useradd --uid 10001 --gid 10001 --no-create-home passit \
    && mkdir /data && chown 10001:10001 /data
COPY --from=dependencies /app/.venv /app/.venv
COPY backend /app/backend
COPY alembic.ini /app/alembic.ini
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "passit.api:app", "--host", "0.0.0.0", "--port", "8000"]
