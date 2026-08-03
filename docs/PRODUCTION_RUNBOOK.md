# PAAC Production Runbook

## Deployment

### Prerequisites
- Docker 24+ and Docker Compose v2+
- Linux host (RLIMIT_AS enforcement requires Linux)
- 4 GB RAM minimum (2 GB reserved for PAAC container)
- Redis 7.0+ with `appendonly yes`

### Build and Deploy

```bash
# Build production image
docker build -t paac:production -f docker/Dockerfile .

# Verify Z3 is available
docker run --rm paac:production python3.11 -c "import z3; print(z3.get_version_string())"

# Start with Docker Compose
cp .env.example .env
# Edit .env: set PAAC_API_KEY, REDIS_HOST, etc.
docker-compose -f docker/docker-compose.yml up -d

# Verify health
curl http://localhost:8000/health
```

### Environment Variables (required in production)

| Variable | Value |
|---|---|
| `PAAC_API_KEY` | Random 32+ char secret |
| `REDIS_HOST` | Redis hostname |
| `AXIOM_PATH` | `config/axioms.yaml` |
| `PAAC_WAL_PATH` | `/app/data/checkpoints.wal` |
| `PAAC_REGISTRY_PATH` | `/app/data/live_registry.json` |

---

## Monitoring

### Health Check
```bash
curl http://localhost:8000/health
# Returns: {"status": "healthy", "circuit_breaker": "CLOSED", ...}
```

### Prometheus Metrics
```bash
curl http://localhost:8000/metrics
```

Key metrics:
- `verifications_total{outcome="accepted|rejected|error"}` — request counts
- `verification_latency_seconds` — p50/p95/p99 latency histogram
- `active_verifications` — current in-flight verifications
- `circuit_breaker_state_changes_total` — circuit breaker transitions

### Logs
```bash
docker-compose -f docker/docker-compose.yml logs -f paac_core
# Structured JSON format. Filter by level:
docker-compose logs paac_core | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        r = json.loads(line)
        if r.get('level') in ('ERROR', 'WARNING'):
            print(line.strip())
    except: pass
"
```

### Audit Log
```bash
tail -f audit.log
# Format: timestamp LEVEL ACCEPTED/REJECTED func=<name> citation=<url>
```

---

## Recovery Procedures

### Circuit Breaker Open (HTTP 503)

**Symptom**: All `/verify` requests return 503.

**Cause**: 5+ consecutive verification failures.

**Recovery**:
1. Check logs for root cause: `docker-compose logs paac_core | grep ERROR`
2. Wait 60 seconds for automatic HALF_OPEN transition.
3. Submit one valid verification request to close the circuit.
4. If the root cause is a bad axiom, fix `config/axioms.yaml` and restart.

### Redis Down

**Symptom**: Logs show "Redis is unavailable. Falling back to WAL."

**Recovery**:
1. Restart Redis: `docker-compose restart redis`
2. PAAC automatically reconnects on next request.
3. WAL checkpoints are replayed on PAAC restart.

### Z3 Subprocess Crash Loop

**Symptom**: Logs show "Z3 subprocess crashed" 3 times, then VerificationError.

**Recovery**:
1. Check memory: `docker stats paac_core` — if near 2 GB, increase limit.
2. Check for malformed SIL input in audit.log.
3. Restart PAAC: `docker-compose restart paac_core`

### WAL Corruption

**Symptom**: Logs show "WAL: skipping malformed line".

**Recovery**:
1. PAAC automatically skips corrupt lines and continues.
2. To reset WAL: `docker exec paac_core truncate -s 0 /app/data/checkpoints.wal`
3. Registry state is preserved in `live_registry.json`.

### Full Service Restart

```bash
docker-compose -f docker/docker-compose.yml down
docker-compose -f docker/docker-compose.yml up -d
```

State is preserved via WAL and registry files in the `paac_data` volume.

---

## Rollback

PAAC automatically rolls back to the last verified checkpoint on rejection.
To manually inspect checkpoints:

```bash
# View WAL entries
cat /app/data/checkpoints.wal | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line.strip())
    print(r['func_name'], r['timestamp'], r['source_citation'][:40])
"

# View live registry
cat /app/data/live_registry.json
```

---

## Scaling

- Increase `max_concurrent_verifications` (default: 4) for higher throughput.
- Z3 is CPU-bound; scale horizontally with multiple PAAC instances behind a load balancer.
- Redis must be shared across instances for consistent checkpoint state.
- Each instance maintains its own circuit breaker; use a shared Redis key for global state in multi-instance deployments.
