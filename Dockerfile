# Container image for the Housing Nutrition Label API (FastAPI + uvicorn).
# Build:  docker build -t housing-label-api .
# Run:    docker run -p 8000:8000 \
#           -e ALLOWED_ORIGINS=https://housinglabel.dev \
#           housing-label-api          # no API keys required
#         (optional: -e GEOAPIFY_API_KEY=... for sharper address autocomplete)
# Works as-is on Fly.io, Cloud Run, Railway, or any container host.
FROM python:3.11-slim

WORKDIR /app

# Every download is pinned and hash-checked, and in its own layer so a code
# change does not refetch it. Regenerate with the command in the file's header.
COPY requirements-api.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-api.txt

# Copy only what the package needs to install (see pyproject's packages/readme).
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

# Offline, so it fails if pyproject needs something the lock above lacks.
RUN pip install --no-cache-dir --no-index --no-build-isolation ".[api]"

# Hosts (Render/Cloud Run/Fly) inject $PORT; default to 8000 locally.
ENV PORT=8000
# CORS default — override at deploy time for a different origin.
ENV ALLOWED_ORIGINS=https://housinglabel.dev
# Deliberately NOT set: FORWARDED_ALLOW_IPS. uvicorn trusts X-Forwarded-For only
# from a peer in that list (default 127.0.0.1), so behind a proxy that is not on
# loopback every caller arrives as the proxy and shares one rate-limit bucket.
# Set FORWARDED_ALLOW_IPS="*" ONLY where the container is reachable exclusively
# through a trusted proxy (as render.yaml does). On a host that publishes this
# port directly it would let any caller spoof their address and evade the limit.
EXPOSE 8000

# The API writes nothing to disk, so it needs no write access anywhere.
USER nobody

CMD ["sh", "-c", "uvicorn housing_label.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
