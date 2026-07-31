# Provably Aligned AI Core (PAAC)

PAAC is a deterministic safety wrapper for self-improving agents, mathematically guaranteeing that AI-proposed code modifications preserve safety properties via Formal Verification.

## Enterprise v2.1 Updates
This release is fully enterprise-ready and containerized, integrating three major production fixes:
1. **Containerized Deployment (Alpine)**: PAAC is now deployed natively in an Alpine Linux Docker container, fundamentally eliminating OS-specific library loading issues (such as AppLocker blocking `libz3.dll` on Windows).
2. **Extended SIL Standard Library**: The Safe Intermediate Language (SIL) grammar has been securely extended. It now supports bounded deterministic array primitives (`length`, `map`, `filter`, `concat`) and standard math operators (`max`, `min`). **Honest Note**: Recursion remains unsupported by design to guarantee loop termination for bounded model checking.
3. **Distributed Rollback via Redis**: The `CodeMonitor` state and rollback mechanism has been refactored to use Redis for distributed, scalable persistence. The `Watchdog` health check monitors Redis, automatically failing over to an in-memory degraded mode if the network connection drops.

## Quick Start
```bash
docker-compose up -d
docker exec -it paac_container bash
paac-cli verify examples/bubble_sort.sil
```

## Security Profile
- Bounded Model Checker: Z3 Prover (Incremental Mode)
- Hallucination Prevention: Semantic Grounding with Mandatory Citations
- Recovery: Distributed Redis Checkpointing / In-memory Fallback
