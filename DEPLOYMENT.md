# PAAC Deployment Guide

Copyright (c) 2026 Shashank Kumar. All rights reserved.

## Prerequisites
- Python 3.12+
- Z3 Solver installed at system level (ensure libz3 is in PATH)
- OpenTelemetry Collector (for distributed tracing)
- Prometheus (for metrics scraping)

## Configuration
Configure `config/default.yaml` with the appropriate Gemini API key and hardware constraints for your execution environment.

## Execution
Run the verification API in production using Gunicorn/Uvicorn:
`uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4`

## Security
The execution host MUST run within an airgapped or heavily firewalled sandbox. Ensure the PAAC process runs as a restricted user to prevent the Inner Agent from tampering with PAAC's memory limits.
