# Dockerfile
# Copyright (c) 2026 Shashank Kumar. All rights reserved.

# Stage 1: Build dependencies
FROM python:3.12-alpine AS builder

WORKDIR /app
COPY requirements.txt .

RUN apk add --no-cache gcc musl-dev z3-dev && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-alpine

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Remove any traces of temp directories or git
RUN rm -rf /tmp/*_fetch && \
    find . -name ".git" -type d -exec rm -rf {} + || true

ENTRYPOINT ["python", "src/cli.py"]
