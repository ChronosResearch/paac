# PAAC Troubleshooting Guide

## Common Errors

### `ConfigurationError: No safety axioms loaded`

**Cause**: `config/axioms.yaml` is missing, empty, or has invalid YAML.

**Fix**:
```bash
# Verify the file exists and is valid
python3.11 -c "import yaml; yaml.safe_load(open('config/axioms.yaml'))"
# Check AXIOM_PATH env var points to the correct file
echo $AXIOM_PATH
```

---

### `VerificationError: Z3 solver returned unknown/timeout`

**Cause**: Z3 exceeded the 5-second timeout on a complex formula.

**Fix**:
1. Increase timeout: set `PAAC_VERIFICATION_TIMEOUT_MS=10000`
2. Simplify the SIL program — reduce loop bounds or assertion complexity.
3. Check if the program has many nested loops (each unrolled up to `bound` times).

---

### `VerificationError: Axiom '<id>' could not be encoded`

**Cause**: An axiom condition references a variable not declared as a function parameter.

**Fix**: Ensure the axiom condition uses only variable names that appear as parameters
in the functions being verified. Example:
```yaml
# Wrong — 'x' is not a parameter of 'compute'
- id: "result_positive"
  condition: "x >= 0"
  target_functions: ["compute"]

# Correct — 'result' is a parameter of 'compute'
- id: "result_positive"
  condition: "result >= 0"
  target_functions: ["compute"]
```

---

### `SILError: Recursion cycle detected`

**Cause**: SIL does not allow recursion (direct or mutual).

**Fix**: Rewrite recursive functions as iterative loops with explicit bounds:
```
# Wrong
func fib(n: int) -> int { return fib(n-1) + fib(n-2); }

# Correct
func fib(n: int) -> int {
    a = 0; b = 1; i = 0;
    while (i < n) bound 100 {
        tmp = b; b = a + b; a = tmp; i = i + 1;
    }
    return a;
}
```

---

### `SILError: Loop bound must be positive` / `Expected token type KEYWORD`

**Cause**: A `while` loop is missing the `bound N` clause.

**Fix**: All while loops in SIL require an explicit bound:
```
while (condition) bound 100 { ... }
```

---

### `SILRuntimeError: Instruction limit exceeded`

**Cause**: The program exceeded 100,000 instructions (global cap).

**Fix**: Reduce loop bounds or split the computation into smaller functions.
Override the limit for testing: `PAAC_MAX_INSTRUCTIONS=500000` (not recommended for production).

---

### `CircuitOpenError: Circuit breaker is OPEN`

**Cause**: 5+ consecutive verification failures.

**Fix**: Wait 60 seconds for automatic HALF_OPEN, then submit a valid request.
Check logs for the root cause of the failures.

---

### `HTTP 401: Invalid or missing API key`

**Cause**: `PAAC_API_KEY` is set but the request is missing `X-API-Key` header.

**Fix**:
```bash
curl -H "X-API-Key: your-key" http://localhost:8000/verify -d '...'
```

---

### `HTTP 429: Rate limit exceeded`

**Cause**: More than 100 requests/minute from the same IP.

**Fix**: Implement request queuing on the client side, or increase the limit:
`PAAC_RATE_LIMIT=500`

---

### `HTTP 400: Validation error`

**Cause**: Malformed JSON or missing required fields in the request body.

**Fix**: Ensure the request body matches the schema:
```json
{
  "func_name": "my_func",
  "old_code": "...",
  "new_code": "func my_func(x: int) -> int { return x; }",
  "pre_cond": "",
  "post_cond": "",
  "source_citation": "https://doi.org/10.1234/example"
}
```

---

### Redis connection errors in logs

**Cause**: Redis is not running or not reachable at `REDIS_HOST:REDIS_PORT`.

**Fix**: PAAC degrades gracefully to WAL mode. To restore Redis:
```bash
docker-compose restart redis
```

---

### `GroundingError: source_citation must be at least 20 characters`

**Cause**: The `source_citation` field is too short or missing a dot.

**Fix**: Provide a full URL or DOI:
```json
"source_citation": "https://doi.org/10.1234/example"
```

To disable citation enforcement (development only):
```yaml
# config/default.yaml
grounding:
  require_source_citations: false
```

---

## Diagnostic Commands

```bash
# Check service health
curl http://localhost:8000/health | python3 -m json.tool

# View Prometheus metrics
curl http://localhost:8000/metrics | grep verifications

# Tail audit log
tail -f audit.log

# Run tests
PYTHONPATH=. python3.11 -m pytest tests/ -v

# Check bandit
python3.11 -m bandit -r src/ -ll

# Check mypy
python3.11 -m mypy src/ --ignore-missing-imports
```
