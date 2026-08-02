# PAAC Deployment Guide

## Prerequisites

- Docker 24+ and Docker Compose v2+
- 4 GB RAM minimum (2 GB reserved for the PAAC container)
- Linux host recommended (RLIMIT_AS enforcement requires Linux)
- Redis 7.0+ (provided by docker-compose)

## Build

```bash
docker build -t paac:latest -f docker/Dockerfile .
```

Verify Z3 is available inside the image:

```bash
docker run --rm paac:latest python3.11 -c "import z3; print(z3.get_version_string())"
```

## Run

```bash
cp .env.example .env
# Edit .env if your Redis host differs from the default.
docker-compose -f docker/docker-compose.yml up -d
```

The PAAC service starts, loads axioms from `config/axioms.yaml`, and listens
for verification requests. Logs are written to stdout and captured by Docker.

To tail logs:

```bash
docker-compose -f docker/docker-compose.yml logs -f paac_core
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `REDIS_HOST` | Yes | `redis` | Redis hostname |
| `REDIS_PORT` | No | `6379` | Redis port |
| `AXIOM_PATH` | No | `config/axioms.yaml` | Axiom file path inside the container |
| `VERIFICATION_TIMEOUT_MS` | No | `5000` | Z3 solver timeout per query in milliseconds |

## Configuration

Runtime configuration is in `config/default.yaml`. The file does not contain
secrets or host-specific paths. All host-specific values are set via
environment variables listed above.

## Axiom Management

Safety axioms are defined in `config/axioms.yaml`. The file uses a flat list
format:

```yaml
axioms:
  - id: "my_axiom"
    description: "Human-readable description"
    condition: "x >= 0"
    target_functions: ["*"]
```

The `condition` field must be a valid SIL boolean expression. The verifier
parses it at startup. If the condition cannot be parsed, the axiom is skipped
and a warning is logged. If no axioms load successfully, the system refuses
to start.

## Known Deployment Limitation (R-1)

Z3 runs in a subprocess. The subprocess has `RLIMIT_AS` (1 GB address space)
and `RLIMIT_CPU` (5 seconds) set via `resource.setrlimit`. These limits are
enforced on Linux. On macOS, `RLIMIT_AS` is not enforced by the kernel.

For production deployments on any platform, run the PAAC service inside a
container with a hard memory limit:

```bash
docker run --memory=2g --cpus=2 paac:latest
```

This enforces the memory limit at the cgroup level, independent of the
in-process resource limits.

Until this is the standard deployment configuration, the system is
CONDITIONALLY GO for development and internal testing only.

## Monitoring

Logs are written to stdout in loguru format. To persist logs to a file:

```bash
docker run --memory=2g paac:latest 2>&1 | tee logs/paac.log
```

There is no built-in metrics endpoint in this prototype. Add a Prometheus
exporter or structured log aggregation before production deployment.

## Rollback

On verification failure, the system attempts to restore the last verified
checkpoint from Redis. If Redis is unavailable, it falls back to an in-memory
checkpoint store. In-memory checkpoints are lost on process restart.

For production, ensure Redis is highly available and persistent
(`appendonly yes` in redis.conf).
