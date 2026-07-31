# PAAC Deployment Guide

## Prerequisites
- **Redis Server (7.0+)**: Required for the Code Monitor check-pointing and self-healing systems. If not installed natively, use Docker Compose.
- **Python 3.12+**: The PAAC prototype requires modern Python features.

## Installation
Use the provided `docker-compose.yml` to deploy PAAC with Redis locally.

```bash
docker-compose up -d
```
