# PAAC Deployment Guide — v5.0.0

## Prerequisites

- Docker 24+ and Docker Compose v2+
- 4 GB RAM minimum (2 GB reserved for the PAAC container)
- Linux host (RLIMIT_AS enforcement and TCB file protection require Linux)
- Redis 7.0+ with `appendonly yes` (provided by docker-compose)

## What Changed in v5.0.0

### Critical fixes

| Fix | Description |
|---|---|
| C-01 Duplicate loop violation | Removed duplicate `still_running` flag in `StmtEncoder` |
| H-01 No eval() in runtime | Runtime axiom evaluator uses SIL compiler+runtime |
| H-02 Duplicate param detection | Type checker rejects duplicate parameter names |
| H-03 Missing return warning | Compile-time warning for functions without `return` |

### New features

| Feature | Description |
|---|---|
| PCM | Proof-Carrying Modification — agents submit formal proofs |
| PCM Certificates | HMAC-SHA256 certificates for every accepted proof |
| Axiom Coverage | Measures which axioms are actively evaluated |
| CEGAR Repair | Automatic axiom strengthening from counterexamples |
| Differential Verification | Conservative extension proofs between versions |
| Mutation Testing | Axiom robustness score via mutation operators |

## Fail-Safe Systems

### Circuit Breaker
Opens after 5 consecutive verification failures. All modifications are rejected
with HTTP 503 for 60 s. After cooldown, one probe is allowed; success closes
the circuit.

### Write-Ahead Log (WAL)
Every accepted checkpoint is written to `checkpoints.wal` before Redis. On
startup, the WAL is replayed to restore the last known-good state for each
function. Set `PAAC_WAL_PATH` to override.

### Registry Persistence
The live function registry is saved to `live_registry.json` after every
accepted modification. Set `PAAC_REGISTRY_PATH` to override.

### Z3 Crash Recovery
If the Z3 subprocess exits with a non-zero code, the parent retries up to
3 times. After 3 consecutive crashes, VerificationError is raised and the
circuit breaker records a failure.

### IPC Authentication
A random 32-byte token is generated per verification call. The subprocess
echoes it back; the parent rejects any response with a wrong token.

### TCB File Protection
On Linux, TCB source files are chmod'd read-only at startup. Deploy with
`docker run --read-only` and as a non-root user for stronger guarantees.

## Build

```bash
docker build -t paac:v5.0.0 -f docker/Dockerfile .
```

Verify Z3 is available:

```bash
docker run --rm paac:v5.0.0 python3.11 -c "import z3; print(z3.get_version_string())"
```

## Run

```bash
cp .env.example .env
# Edit .env — set PAAC_API_KEY, PAAC_CERT_KEY, PAAC_ATTEST_KEY
docker-compose -f docker/docker-compose.yml up -d
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `REDIS_HOST` | Yes | `redis` | Redis hostname |
| `REDIS_PORT` | No | `6379` | Redis port |
| `AXIOM_PATH` | No | `config/axioms.yaml` | Axiom file path |
| `PAAC_API_KEY` | **Yes (prod)** | `` | API key for X-API-Key header auth |
| `PAAC_CERT_KEY` | **Yes (prod)** | *(insecure default)* | HMAC key for PCM certificates (hex 32 bytes) |
| `PAAC_ATTEST_KEY` | **Yes (prod)** | *(ephemeral)* | HMAC key for attestation (hex 32 bytes) |
| `PAAC_PCM_MODE` | No | `false` | Require proofs with every modification |
| `PAAC_PCM_LOG` | No | `pcm_audit.jsonl` | PCM certificate audit log path |
| `VERIFICATION_TIMEOUT_MS` | No | `5000` | Z3 solver timeout per query (ms) |
| `PAAC_RATE_LIMIT` | No | `100` | Requests per minute per IP |
| `PAAC_WAL_PATH` | No | `checkpoints.wal` | Write-ahead log file path |
| `PAAC_REGISTRY_PATH` | No | `live_registry.json` | Registry persistence file path |
| `PAAC_WATCHDOG_TIMEOUT` | No | `60` | Watchdog stall timeout (seconds) |
| `PAAC_MAX_LOOP_BOUND` | No | `10000` | Global loop bound cap |
| `PAAC_MAX_INSTRUCTIONS` | No | `100000` | Global instruction limit |

## Axiom Management

Safety axioms are defined in `config/axioms.yaml`. The `target_functions` field
is enforced (A-05 fix): axioms are only applied to the functions they name.

```yaml
axioms:
  - id: "no_negative_balance"
    description: "Account balance must remain non-negative."
    condition: "balance >= 0"
    target_functions: ["withdraw", "deposit", "transfer"]
```

Use `target_functions: ["*"]` or an empty list `[]` to apply an axiom globally.

## PCM Configuration

To enable Proof-Carrying Modification mode:

```bash
# In .env
PAAC_PCM_MODE=true
PAAC_PCM_LOG=/app/data/pcm_audit.jsonl
PAAC_CERT_KEY=<hex-encoded 32-byte random key>
```

In PCM mode, every modification must include a PPL proof. The proof checker
runs in pure Python (no Z3) and completes in <10ms. Accepted proofs generate
a PCM certificate appended to the audit log.

Generate a proof for a SIL file:

```bash
PYTHONPATH=. python3.11 -m src.cli pcm-generate examples/safe.sil --out proof.json
```

Submit a modification with proof:

```bash
PYTHONPATH=. python3.11 -m src.cli pcm-submit examples/safe.sil proof.json \
  --agent-id my-agent --cert-out cert.json --log pcm_audit.jsonl
```

Query the audit log:

```bash
PYTHONPATH=. python3.11 -m src.cli pcm-audit --log pcm_audit.jsonl
```

## Certificate Storage

PCM certificates are stored in an append-only JSONL file (`pcm_audit.jsonl`
by default). Each line is a JSON-serialised `PCMCertificate`.

For production deployments, mount the certificate log on persistent storage:

```yaml
# docker-compose.yml
volumes:
  - paac_data:/app/data
environment:
  - PAAC_PCM_LOG=/app/data/pcm_audit.jsonl
```

Third parties can verify certificates without access to PAAC — they only need
the shared HMAC key (`PAAC_CERT_KEY`).

## Monitoring

- `/health` — returns `healthy` / `degraded` / `unhealthy` with circuit breaker state
- `/metrics` — Prometheus metrics (verifications_total, latency histogram, active gauge)
- `audit.log` — append-only audit log of all accepted/rejected modifications
- `paac_core.log` — structured JSON debug log (rotates at 10 MB)
- `pcm_audit.jsonl` — PCM certificate audit log (append-only JSONL)

## Known Deployment Limitation

Z3 runs in a subprocess with `RLIMIT_AS` (1 GB) and `RLIMIT_CPU` (5 s) on
Linux. On macOS, `RLIMIT_AS` is not enforced by the kernel.

For production deployments on any platform:

```bash
docker run --memory=2g --cpus=2 paac:v5.0.0
```
