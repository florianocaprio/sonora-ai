# syntax=docker/dockerfile:1

FROM node:22.23.2-bookworm-slim AS frontend
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY services/api/package.json services/api/package.json
RUN npm install --global pnpm@10.34.5 \
    && pnpm --filter @sonora/web... install --frozen-lockfile
COPY apps/web/ apps/web/
RUN pnpm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SONORA_DATA_DIR=/var/lib/sonora/data \
    SONORA_MODEL_DIR=/var/lib/sonora/models \
    SONORA_PORT=8765
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sonora \
    && useradd --uid 10001 --gid sonora --create-home --shell /usr/sbin/nologin sonora \
    && install -d -m 0700 -o sonora -g sonora /var/lib/sonora/data /var/lib/sonora/models

COPY requirements-linux-cpu.lock ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements-linux-cpu.lock \
    && python -m pip check \
    && python -c "import torch, torchaudio; assert torch.version.cuda is None; assert not torch.backends.mps.is_built()"
COPY THIRD_PARTY_NOTICES.md ./
COPY services/ services/
COPY configs/ configs/
COPY packages/ packages/
COPY --from=frontend /src/apps/web/dist/ apps/web/dist/
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log", "--no-proxy-headers"]
