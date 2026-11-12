# Incident Root-Cause Agent

An agent that investigates an alert like an on-call engineer (logs, metrics, traces),
forms hypotheses, tests them with more queries, and returns a ranked list of likely causes
with evidence. Evaluated against faults injected into a demo microservice app.

## Status: milestone 1 of 5 (~20%)

- [x] **Demo system**: gateway, orders, payments, inventory, MySQL, load generator
- [x] **Observability**: Prometheus (metrics), Loki + Promtail (logs), Tempo (traces), Grafana
- [x] **Fault hooks** in every service via `POST /admin/fault`
- [x] Prometheus alert rules, smoke test
- [ ] Fault injector with ground-truth records (2 faults first)
- [ ] Agent tools with plain-code summaries + non-LLM baseline
- [ ] LLM loop with cited evidence
- [ ] Evaluation harness, remaining faults, write-up

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2), 6-8 GB RAM allotted
- Python 3.11+ (only needed on the host to run the smoke test and, later, the agent)
- Free ports: 3000, 3100, 3200, 8000-8003, 9090

## Quick start

```bash
make venv && source .venv/bin/activate    # host python deps (httpx etc.)
make up                                   # first build takes a few minutes
make smoke                                # waits for everything and checks all 3 signals
```

Then open Grafana at http://localhost:3000 (no login) -> Dashboards -> **RCA Demo Overview**.
In Explore you can query Loki and Tempo; log lines with a `trace_id` link straight to the trace.

| What | URL |
|---|---|
| Grafana | http://localhost:3000 |
| Prometheus (+ alerts) | http://localhost:9090 |
| Loki / Tempo APIs | http://localhost:3100 / http://localhost:3200 |
| gateway / orders / payments / inventory | :8000 / :8001 / :8002 / :8003 |

## Architecture

```
locust -> gateway -> orders -> inventory -> MySQL
                         \---> payments  -> MySQL
every service: /metrics (Prometheus), JSON logs -> Promtail -> Loki, OTLP traces -> Tempo
```

Alert you will investigate: `CheckoutLatencyHigh` (gateway `/checkout` p95 > 0.5s), defined in
`demo/observability/rules.yml`.

## Injecting faults by hand

Every service exposes the same admin API (the future injector script just calls this):

```bash
# slow DB on orders: each DB connection is held 800 ms (SELECT SLEEP), which also drains the pool
curl -X POST localhost:8001/admin/fault -H 'content-type: application/json' -d '{"slow_db_ms": 800}'

# bad deploy on payments: new version + 30% errors (logs a `deploy` event, bumps app_version_info)
curl -X POST localhost:8002/admin/fault -H 'content-type: application/json' \
     -d '{"version": "v1.4.2", "error_rate": 0.3}'

# downstream timeout: payments hangs longer than orders' 2s client timeout
curl -X POST localhost:8002/admin/fault -H 'content-type: application/json' -d '{"latency_ms": 4000}'

# memory leak on inventory (container limit is 512 MB, so it will eventually OOM and restart)
curl -X POST localhost:8003/admin/fault -H 'content-type: application/json' -d '{"leak_mb_per_s": 5}'

make reset      # clear everything
```

Fields: `slow_db_ms`, `latency_ms`, `error_rate` (0-1), `leak_mb_per_s`, `version`.

**Design choice:** injecting a fault is *not* logged and not exposed as a metric, so the agent
cannot read the answer. The only fault-adjacent signal is a version change, which logs a
`deploy` event, because a real change log would show it too.

## Useful commands

```bash
make logs S=orders        # tail one service
make ps                   # container status
make clean                # wipe containers and volumes
```

## Troubleshooting

- **No logs in Loki:** Promtail reads the Docker socket. On Linux, make sure your user can access
  `/var/run/docker.sock`; on Docker Desktop it works out of the box. Check `make logs S=promtail`.
- **Services restart-looping on first start:** MySQL init takes ~20-30 s; compose waits on its
  healthcheck, but a slow machine may need `make down && make up`.
- **Tempo shows no traces for ~30 s:** ingestion is batched; the smoke test retries.
- **Port already in use:** change the left side of the port mappings in `demo/docker-compose.yml`.
