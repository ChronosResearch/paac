FROM python:3.11-slim

# Step 60: Run as non-root user
RUN groupadd -r paac && useradd -r -g paac -d /app -s /sbin/nologin paac

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: z3-solver && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the non-root user owns the app directory
RUN chown -R paac:paac /app

ENV REDIS_HOST=redis
ENV REDIS_PORT=6379
ENV AXIOM_PATH=config/axioms.yaml
ENV PYTHONPATH=/app

# Step 59: Docker HEALTHCHECK
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3.11 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

USER paac

CMD ["python3.11", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
