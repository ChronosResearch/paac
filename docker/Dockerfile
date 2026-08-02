FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: z3-solver && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV REDIS_HOST=redis
ENV REDIS_PORT=6379
ENV AXIOM_PATH=config/axioms.yaml
ENV PYTHONPATH=/app

CMD ["python3.11", "-m", "pytest", "tests/test_verifier.py", "tests/test_sil_compiler.py", "tests/test_sil_runtime.py", "-v"]
