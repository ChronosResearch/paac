# PAAC Monitoring Guide

## Prometheus Metrics

Metrics are exposed at `GET /metrics` in Prometheus text format.

### Counters

| Metric | Labels | Description |
|---|---|---|
| `verifications_total` | `outcome={accepted,rejected,error}` | Total verification requests |
| `verification_errors_total` | — | Total Z3/compilation errors |
| `circuit_breaker_state_changes_total` | `state={OPEN,CLOSED,HALF_OPEN}` | Circuit breaker transitions |

### Histograms

| Metric | Buckets | Description |
|---|---|---|
| `verification_latency_seconds` | 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10 | End-to-end verification latency |

### Gauges

| Metric | Description |
|---|---|
| `active_verifications` | Currently in-flight verification requests |

---

## Recommended Alerts

### Critical

```yaml
# Circuit breaker open
- alert: PaacCircuitBreakerOpen
  expr: circuit_breaker_state_changes_total{state="OPEN"} > 0
  for: 0m
  annotations:
    summary: "PAAC circuit breaker is OPEN — all verifications suspended"

# High error rate
- alert: PaacHighErrorRate
  expr: rate(verification_errors_total[5m]) > 0.1
  for: 2m
  annotations:
    summary: "PAAC verification error rate > 0.1/s"
```

### Warning

```yaml
# High latency
- alert: PaacHighLatency
  expr: histogram_quantile(0.95, rate(verification_latency_seconds_bucket[5m])) > 5
  for: 5m
  annotations:
    summary: "PAAC p95 verification latency > 5s"

# Active verifications near limit
- alert: PaacConcurrencyNearLimit
  expr: active_verifications > 3
  for: 1m
  annotations:
    summary: "PAAC active verifications near concurrency limit (4)"
```

---

## Grafana Dashboard

Import the dashboard from `docs/grafana_dashboard.json`.

Key panels:
1. **Verification Rate** — `rate(verifications_total[1m])` by outcome
2. **Latency Heatmap** — `verification_latency_seconds` histogram
3. **Active Verifications** — `active_verifications` gauge
4. **Circuit Breaker State** — `circuit_breaker_state_changes_total`
5. **Error Rate** — `rate(verification_errors_total[5m])`

---

## Log Aggregation

PAAC emits structured JSON logs. Ingest with Loki, Elasticsearch, or CloudWatch.

Example Loki query for rejections:
```
{app="paac"} |= "REJECTED"
```

Example for counterexamples:
```
{app="paac"} | json | counterexample != ""
```

---

## Health Check Integration

```bash
# Kubernetes liveness probe
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 30
  failureThreshold: 3

# Kubernetes readiness probe
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```
