FROM node:24-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ARG COPE_DEPLOY_COMMIT=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COPE_DEPLOY_COMMIT=${COPE_DEPLOY_COMMIT} \
    COPE_DB_PATH=/data/cope.db
WORKDIR /app
RUN groupadd --system --gid 10001 cope \
    && useradd --system --uid 10001 --gid cope --home-dir /app cope
COPY pyproject.toml MANIFEST.in ./
COPY cope/ ./cope/
COPY --from=frontend-build /src/cope/web/frontend_dist/ ./cope/web/frontend_dist/
RUN python -m pip install --no-cache-dir ".[web,runner,worker]" \
    && mkdir -p /data /backups \
    && chown -R cope:cope /data /backups /app
USER cope
EXPOSE 8701 8702
ENTRYPOINT ["cope"]
CMD ["web", "--host", "0.0.0.0", "--port", "8701"]
