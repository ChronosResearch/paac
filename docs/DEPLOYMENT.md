# PAAC Deployment Guide — v4.2.0

## Prerequisites

- Docker 24+ and Docker Compose v2+
- 4 GB RAM minimum (2 GB reserved for the PAAC container)
- Linux host (RLIMIT_AS enforcement and TCB file protection require Linux)
- Redis 7.0+ with `appendonly yes` (provided by docker-compose)

## What Changed in v4.2.0

Five critical security issues fixed (see `SECURITY.md` for full details):

| Fix | Description |
|---|---|
| A-01 Loop soundness | Under-bounded loops now correctly return SAT |
| A-02 Cache hardening | `__cache` name-mangled; read-only property prevents poisoning |
| A-03 Timing attack | API key comparison uses `secrets.compare_digest` |
| A-04 Spawn start method | `multiprocessing.set_start_method("spawn")` prevents fork-under-threads |
| A-05 Axiom scoping | `_get_applicable_axioms()` filters by `target_functions` |

Seven advanced research features added (see `ADVANCED_FEATURES_REPORT.md`).

## Fail-Safe Systems

### Circuit Breaker
Opens after 5 consecutive verification failures. All modifications are rejected
with HTTP 503 for 60 s. After cooldown, one probe is allowed; success closes
the circuit.

### Write-Ahead Log (WAL)
Every accepted checkpoint is written to `checkpoints.wal` before Redis. On
startup, the WAL is replayed to restore the last known-good state for each
function. Set `PAAC_WAL_PATH` to override the default path.

### Registry Persistence
The live function registry is saved to `live_registry.json` after every
accepted modification. On startup, it is loaded before the WAL replay.
Set `PAAC_REGISTRY_PATH` to override.

### Z3 Crash Recovery
If the Z3 subprocess exits with a non-zero code, the parent retries up to
3 times. After 3 consecutive crashes, VerificationError is raised and the
circuit breaker records a failure.

### IPC Authentication
A random 32-byte token is generated per verification call. The subprocess
echoes it back; the parent rejects any response with a wrong token.

### TCB File Protection
On Linux, TCB source files are chmod'd read-only at startup. This is a
filesystem-level protection only (not kernel read-only memory pages). Deploy
with `docker run --read-only` and as a non-root user for stronger guarantees.

### Multiprocessing Safety (A-04)
`multiprocessing.set_start_method("spawn", force=True)` is called at import
time in `src/main.py`. This ensures Z3 subprocesses do not inherit open file
descriptors or partially-initialised thread state from the parent process.

## Build

```bash
docker build -t paac:v4.2.0 -f docker/Dockerfile .
```

Verify Z3 is available inside the image:

```bash
docker run --rm paac:v4.2.0 python3.11 -c "import z3; print(z3.get_version_string())"
```

## Run

```bash
cp .env.example .env
# Edit .env — set PAAC_API_KEY to a strong random value
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
| `PAAC_API_KEY` | Yes (prod) | `` | API key for X-API-Key header auth |
| `PAAC_RATE_LIMIT` | No | `100` | Requests per minute per IP |
| `VERIFICATION_TIMEOUT_MS` | No | `5000` | Z3 solver timeout per query in milliseconds |
| `PAAC_WAL_PATH` | No | `checkpoints.wal` | Write-ahead log file path |
| `PAAC_REGISTRY_PATH` | No | `live_registry.json` | Registry persistence file path |
| `PAAC_WATCHDOG_TIMEOUT` | No | `60` | Watchdog stall timeout in seconds |

## Axiom Management

Safety axioms are defined in `config/axioms.yaml`. The `target_functions` field
is now enforced (A-05 fix): axioms are only applied to the functions they name.

```yaml
axioms:
  - id: "no_negative_balance"
    description: "Account balance must remain non-negative."
    condition: "balance >= 0"
    target_functions: ["withdraw", "deposit", "transfer"]
```

Use `target_functions: ["*"]` or an empty list `[]` to apply an axiom globally.

## Known Deployment Limitation

Z3 runs in a subprocess with `RLIMIT_AS` (1 GB) and `RLIMIT_CPU` (5 s) on
Linux. On macOS, `RLIMIT_AS` is not enforced by the kernel.

For production deployments on any platform:

```bash
docker run --memory=2g --cpus=2 paac:v4.2.0
```

## Monitoring

- `/health` — returns `healthy` / `degraded` / `unhealthy` with circuit breaker state
- `/metrics` — Prometheus metrics (verifications_total, latency histogram, active gauge)
- `audit.log` — append-only audit log of all accepted/rejected modifications
- `paac_core.log` — structured JSON debug log (rotates at 10 MB)
