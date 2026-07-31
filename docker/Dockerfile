FROM python:3.14-alpine

# Alpine uses musl which avoids Windows-specific .dll loading issues with Z3.
# Install build dependencies for Z3 and others
RUN apk add --no-cache build-base linux-headers \
    && rm -rf /var/cache/apk/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV REDIS_HOST=redis
ENV REDIS_PORT=6379

CMD ["python", "-m", "pytest", "tests/"]
