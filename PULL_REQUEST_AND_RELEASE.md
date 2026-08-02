# Pull Request and Release Instructions

## Push the Release Branch

The branch `release-v4.0` is committed locally. Push it with:

```bash
git push -u origin release-v4.0
```

If you are using HTTPS and need credentials:

```bash
git remote set-url origin https://<your-token>@github.com/ChronosResearch/paac.git
git push -u origin release-v4.0
```

---

## Pull Request Instructions

1. Go to https://github.com/ChronosResearch/paac/pulls
2. Click "New Pull Request"
3. Set base: `main`, compare: `release-v4.0`
4. Title: `release: PAAC v4.0 - Production Prototype`
5. Description:

```
All critical and high issues from the security audit are resolved.

Changes in this release:
- Real Z3 BMC pipeline: SSA encoding, loop unrolling, path conditions
- Z3 subprocess isolation with RLIMIT_AS (1 GB) and RLIMIT_CPU (5 s)
- Constant-time verification padding (200 ms, all exit paths)
- SHA-256 cache hash (replaces Python hash())
- Mutual recursion detection via full call-graph DFS
- Lexer fails closed on unrecognised characters
- Rollback actually restores state
- Axioms loaded at init; empty axiom set is a fatal error
- black + ruff + mypy: zero errors
- bandit: zero high-severity issues
- Docker image: python:3.11-slim, Z3 4.15.4
- README, DEPLOYMENT.md, SECURITY.md, KNOWN_ISSUES.md added

Remaining open issues: R-1 through R-7 documented in KNOWN_ISSUES.md.
The system is GO for internal testing. NOT production-ready until
docker run --memory=2g is enforced at the deployment level.

Test results: 24/24 pass.
```

6. Request review from the relevant reviewer.
7. Click "Create Pull Request".

---

## Release Instructions

After the PR is merged to `main`:

1. Go to https://github.com/ChronosResearch/paac/releases
2. Click "Create a new release"
3. Tag: `v4.0`
4. Target: `main`
5. Title: `PAAC v4.0 - Prototype Release`
6. Description:

```
PAAC v4.0 is a prototype implementation of a formal verification wrapper
for self-modifying code.

Features:
- Formal verification with Z3 (bounded model checking)
- Safe Intermediate Language (SIL) compiler with type checking
- Safety property database (behavioral, integrity, resource axioms)
- Constant-time verification (200 ms padding on all exit paths)
- Z3 subprocess isolation (RLIMIT_AS 1 GB, RLIMIT_CPU 5 s)
- Checkpoint and rollback via Redis
- Docker deployment (python:3.11-slim)

Limitations:
- Z3 subprocess memory limits are not enforced on macOS.
  Use docker run --memory=2g for production on any platform.
- OS-level read-only memory protection not implemented (R-2).
- IPC authentication not implemented (R-3).
- Source citation validation is not enforced (R-5).

See DEPLOYMENT.md, SECURITY.md, and KNOWN_ISSUES.md for details.
```

7. Click "Publish release".

---

## Deployment Command

```bash
docker run --rm --memory=2g \
  -e REDIS_HOST=your-redis-host \
  -e AXIOM_PATH=config/axioms.yaml \
  paac:release \
  python3.11 -m pytest tests/test_verifier.py tests/test_sil_compiler.py tests/test_sil_runtime.py -v
```
