#!/usr/bin/env python3
"""Verifies the demo stack end to end: services, traffic, metrics, logs, traces, Grafana.

    python scripts/smoke_test.py              # basic checks
    python scripts/smoke_test.py --with-fault # also proves fault injection changes latency
"""
import argparse
import statistics
import sys
import time

import httpx

SVC = {"gateway": 8000, "orders": 8001, "payments": 8002, "inventory": 8003}
PROM, LOKI, TEMPO, GRAFANA = ("http://localhost:9090", "http://localhost:3100",
                              "http://localhost:3200", "http://localhost:3000")
http = httpx.Client(timeout=10)
failed = []


def check(name, fn, retries=1, delay=3):
    detail = ""
    for i in range(retries):
        try:
            ok, detail = fn()
            if ok:
                print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
                return True
        except Exception as e:  # noqa: BLE001
            detail = repr(e)
        if i < retries - 1:
            time.sleep(delay)
    print(f"  FAIL  {name}  ({detail})")
    failed.append(name)
    return False


def health(port):
    def f():
        r = http.get(f"http://localhost:{port}/health")
        return r.status_code == 200, r.text[:80]
    return f


def checkout():
    r = http.post(f"http://localhost:8000/checkout", json={"user_id": 1, "product_id": 1, "qty": 1})
    return r.status_code in (200, 402), f"status {r.status_code}"


def prom_has_traffic():
    r = http.get(f"{PROM}/api/v1/query",
                 params={"query": 'sum(http_requests_total{service="gateway",path="/checkout"})'})
    res = r.json()["data"]["result"]
    return bool(res) and float(res[0]["value"][1]) > 0, f"{len(res)} series"


def prom_targets_up():
    r = http.get(f"{PROM}/api/v1/query", params={"query": "sum(up == 1)"})
    res = r.json()["data"]["result"]
    n = int(float(res[0]["value"][1])) if res else 0
    return n >= 4, f"{n}/4 targets up"


def loki_has_logs():
    r = http.get(f"{LOKI}/loki/api/v1/query_range",
                 params={"query": '{service="gateway"}', "limit": 1})
    res = r.json()["data"]["result"]
    return bool(res), f"{len(res)} streams"


def tempo_has_traces():
    r = http.get(f"{TEMPO}/api/search", params={"limit": 5})
    traces = r.json().get("traces", [])
    return bool(traces), f"{len(traces)} traces"


def grafana_ok():
    r = http.get(f"{GRAFANA}/api/datasources")
    names = sorted(d["name"] for d in r.json())
    return names == ["Loki", "Prometheus", "Tempo"], ",".join(names)


def timed_checkouts(n=10):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        http.post("http://localhost:8000/checkout", json={"user_id": 1, "product_id": 2, "qty": 1})
        times.append(time.perf_counter() - t)
    return statistics.median(times)


def fault_test():
    base = timed_checkouts()
    http.post("http://localhost:8002/admin/fault", json={"latency_ms": 500})
    try:
        slow = timed_checkouts()
    finally:
        http.delete("http://localhost:8002/admin/fault")
    return slow - base > 0.4, f"median {base*1000:.0f}ms -> {slow*1000:.0f}ms"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-fault", action="store_true")
    args = ap.parse_args()

    print("Services")
    for name, port in SVC.items():
        check(f"{name} /health", health(port), retries=10, delay=3)
    check("checkout works end to end", checkout, retries=3, delay=1)

    print("Observability signals (give it up to ~60s after first start)")
    check("prometheus targets up", prom_targets_up, retries=10, delay=5)
    check("prometheus has checkout traffic", prom_has_traffic, retries=10, delay=5)
    check("loki has gateway logs", loki_has_logs, retries=12, delay=5)
    check("tempo has traces", tempo_has_traces, retries=12, delay=5)
    check("grafana datasources provisioned", grafana_ok, retries=6, delay=5)

    if args.with_fault:
        print("Fault injection")
        check("payments latency fault slows checkout", fault_test)

    print()
    if failed:
        print(f"{len(failed)} check(s) failed: {', '.join(failed)}")
        print("Tip: `docker compose -f demo/docker-compose.yml logs <service>`")
        sys.exit(1)
    print("All checks passed. Open Grafana: http://localhost:3000")


if __name__ == "__main__":
    main()
