#!/usr/bin/env python3
"""
Advanced Load Generator for Performance-Based Dynamic Load Balancer Testing
Evaluates the GRP-CHAT system via required routes:
  - POST /message (accepts "client-name" and "msg")
  - GET  /feed    (retrieves all messages)

Supports:
  - Variable number of concurrent users (--users)
  - Random/variable message lengths (--min-len, --max-len)
  - Random/variable time intervals between messages (--min-interval, --max-interval)
  - Message deduplication verification (--test-dedup)
  - Metrics tracking: Latency (p50, p90, p99, mean), Throughput (req/s), Backend Distribution
"""

import argparse
import concurrent.futures
import json
import random
import string
import time
from collections import Counter
import requests

WORDS = [
    "network", "distributed", "system", "performance", "dynamic", "balancer",
    "threshold", "concurrency", "security", "encryption", "signature", "integrity",
    "hashchain", "sqlite", "persistence", "deduplication", "latency", "throughput",
    "message", "feed", "benchmark", "analysis", "realtime", "websocket", "cluster"
]


def generate_random_message(min_len: int, max_len: int) -> str:
    target_len = random.randint(min_len, max_len)
    tokens = []
    current_len = 0
    while current_len < target_len:
        w = random.choice(WORDS)
        tokens.append(w)
        current_len += len(w) + 1
    msg = " ".join(tokens)
    return msg[:target_len].strip()


def percentile(data, p):
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(data):
        return data[f] + (k - f) * (data[c] - data[f])
    return data[f]


def worker_task(user_id: int, base_url: str, num_requests: int,
                min_len: int, max_len: int,
                min_interval: float, max_interval: float,
                feed_ratio: float, timeout: float):
    client_name = f"user_{user_id:03d}"
    records = []

    session = requests.Session()

    for seq in range(num_requests):
        # Determine whether to send /message or /feed
        is_feed = random.random() < feed_ratio

        if is_feed:
            url = f"{base_url.rstrip('/')}/feed"
            t0 = time.perf_counter()
            try:
                resp = session.get(url, timeout=timeout)
                elapsed = time.perf_counter() - t0
                backend = resp.headers.get("X-Backend-ID", "unknown")
                records.append({
                    "type": "feed",
                    "ok": resp.status_code == 200,
                    "status": resp.status_code,
                    "latency": elapsed,
                    "backend": backend,
                    "duplicate": False,
                })
            except Exception as e:
                elapsed = time.perf_counter() - t0
                records.append({
                    "type": "feed",
                    "ok": False,
                    "status": 0,
                    "latency": elapsed,
                    "backend": None,
                    "error": str(e),
                })
        else:
            msg = generate_random_message(min_len, max_len)
            url = f"{base_url.rstrip('/')}/message"
            msg_id = f"gen-{user_id:03d}-{seq:04d}-{int(time.time()*1000)}"
            payload = {
                "client-name": client_name,
                "msg": msg,
                "id": msg_id,
            }
            t0 = time.perf_counter()
            try:
                resp = session.post(url, json=payload, timeout=timeout)
                elapsed = time.perf_counter() - t0
                backend = resp.headers.get("X-Backend-ID", "unknown")
                body = resp.json() if resp.status_code == 200 else {}
                records.append({
                    "type": "message",
                    "ok": resp.status_code in (200, 201),
                    "status": resp.status_code,
                    "latency": elapsed,
                    "backend": backend,
                    "duplicate": body.get("duplicate", False),
                })
            except Exception as e:
                elapsed = time.perf_counter() - t0
                records.append({
                    "type": "message",
                    "ok": False,
                    "status": 0,
                    "latency": elapsed,
                    "backend": None,
                    "error": str(e),
                })

        # Random sleep interval between messages
        interval = random.uniform(min_interval, max_interval)
        time.sleep(interval)

    return records


def run_dedup_test(base_url: str, timeout: float = 5.0):
    """Verifies that sending identical message IDs prevents duplicate DB insertions."""
    print("\n[test] Running Idempotency & Deduplication Test...")
    session = requests.Session()
    url = f"{base_url.rstrip('/')}/message"
    test_id = f"dedup-test-{int(time.time()*1000)}"
    client_name = "test_dedup_user"
    msg_text = "This message is sent 10 times to test deduplication."

    results = []
    for i in range(10):
        try:
            r = session.post(url, json={
                "client-name": client_name,
                "msg": msg_text,
                "id": test_id
            }, timeout=timeout)
            data = r.json()
            results.append((r.status_code, data.get("duplicate")))
        except Exception as e:
            results.append((0, str(e)))

    first_status, first_dup = results[0]
    subsequent_dup = [dup for _, dup in results[1:]]

    print(f"  Attempt 1: Status={first_status}, DuplicateFlag={first_dup}")
    print(f"  Attempts 2-10: All marked duplicate={all(subsequent_dup)}")

    # Verify /feed contains this msg_id exactly once
    # Use a high limit so newly inserted messages are always visible
    feed_r = session.get(f"{base_url.rstrip('/')}/feed?limit=99999", timeout=timeout)
    feed_data = feed_r.json()
    if isinstance(feed_data, dict):
        feed_data = feed_data.get("messages", [])
    count = sum(1 for m in feed_data if m.get("id") == test_id or m.get("msg_id") == test_id)
    print(f"  Verification in /feed: msg_id {test_id} appears exactly {count} time(s).")
    passed = (first_dup is False and all(subsequent_dup) and count == 1)
    if passed:
        print("  DEDUPLICATION TEST PASSED: Zero duplicates inserted.")
    else:
        print("  WARNING: Deduplication test returned unexpected count.")
    return passed


def main():
    parser = argparse.ArgumentParser(description="Performance Load Generator for GRP-CHAT")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:6000", help="Load Balancer URL")
    parser.add_argument("--users", type=int, default=30, help="Number of concurrent users")
    parser.add_argument("--requests-per-user", type=int, default=20, help="Requests per user")
    parser.add_argument("--min-len", type=int, default=15, help="Minimum message length")
    parser.add_argument("--max-len", type=int, default=150, help="Maximum message length")
    parser.add_argument("--min-interval", type=float, default=0.01, help="Minimum interval between requests (seconds)")
    parser.add_argument("--max-interval", type=float, default=0.08, help="Maximum interval between requests (seconds)")
    parser.add_argument("--feed-ratio", type=float, default=0.25, help="Ratio of /feed reads vs /message writes")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout (seconds)")
    parser.add_argument("--test-dedup", action="store_true", help="Run deduplication verification test")
    parser.add_argument("--output-json", type=str, default=None, help="Save detailed run metrics to JSON file")
    args = parser.parse_args()

    print("=" * 65)
    print("GRP-CHAT PERFORMANCE LOAD GENERATOR")
    print("=" * 65)
    print(f"Target URL:            {args.url}")
    print(f"Concurrent Users:      {args.users}")
    print(f"Requests per User:     {args.requests_per_user}")
    print(f"Total Requests:        {args.users * args.requests_per_user}")
    print(f"Message Length Range:  {args.min_len} to {args.max_len} chars")
    print(f"Interval Range:        {args.min_interval*1000:.0f}ms to {args.max_interval*1000:.0f}ms")
    print(f"Feed Read Ratio:       {args.feed_ratio*100:.1f}%")
    print("=" * 65)

    if args.test_dedup:
        run_dedup_test(args.url, args.timeout)

    print("\n[start] Launching load test workers...")
    t_start = time.perf_counter()

    all_records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as executor:
        futures = [
            executor.submit(
                worker_task,
                user_id=u,
                base_url=args.url,
                num_requests=args.requests_per_user,
                min_len=args.min_len,
                max_len=args.max_len,
                min_interval=args.min_interval,
                max_interval=args.max_interval,
                feed_ratio=args.feed_ratio,
                timeout=args.timeout,
            )
            for u in range(args.users)
        ]
        for f in concurrent.futures.as_completed(futures):
            all_records.extend(f.result())

    t_total = time.perf_counter() - t_start

    # Compute metrics
    total_reqs = len(all_records)
    successful = [r for r in all_records if r["ok"]]
    failed = [r for r in all_records if not r["ok"]]
    latencies = sorted([r["latency"] * 1000.0 for r in successful])  # in ms

    backend_counter = Counter(r["backend"] for r in successful if r.get("backend"))
    throughput = len(successful) / t_total if t_total > 0 else 0.0

    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p50_lat = percentile(latencies, 50)
    p90_lat = percentile(latencies, 90)
    p95_lat = percentile(latencies, 95)
    p99_lat = percentile(latencies, 99)
    min_lat = latencies[0] if latencies else 0.0
    max_lat = latencies[-1] if latencies else 0.0

    print("\n" + "=" * 65)
    print("BENCHMARK EVALUATION RESULTS")
    print("=" * 65)
    print(f"Total Completed Requests: {total_reqs}")
    print(f"Successful Requests:      {len(successful)} ({(len(successful)/total_reqs)*100:.2f}%)")
    print(f"Failed Requests:          {len(failed)}")
    print(f"Total Elapsed Time:       {t_total:.3f} s")
    print(f"System Throughput:        {throughput:.2f} requests/sec")
    print("-" * 65)
    print("LATENCY METRICS (Round-Trip Response Time):")
    print(f"  Mean Latency:           {mean_lat:.2f} ms")
    print(f"  Min Latency:            {min_lat:.2f} ms")
    print(f"  p50 (Median):           {p50_lat:.2f} ms")
    print(f"  p90:                    {p90_lat:.2f} ms")
    print(f"  p95:                    {p95_lat:.2f} ms")
    print(f"  p99:                    {p99_lat:.2f} ms")
    print(f"  Max Latency:            {max_lat:.2f} ms")
    print("-" * 65)
    print("BACKEND TRAFFIC DISTRIBUTION (Dynamic Load Balancing Proof):")
    total_tagged = sum(backend_counter.values())
    for backend, count in backend_counter.most_common():
        pct = (count / total_tagged) * 100 if total_tagged else 0.0
        bar = "#" * int(pct / 2.5)
        print(f"  {backend:22s}: {count:5d} reqs ({pct:5.1f}%)  |{bar}")
    print("=" * 65)

    if args.output_json:
        result_data = {
            "url": args.url,
            "users": args.users,
            "requests_per_user": args.requests_per_user,
            "total_requests": total_reqs,
            "successful": len(successful),
            "failed": len(failed),
            "duration_sec": t_total,
            "throughput_rps": throughput,
            "latency_ms": {
                "mean": mean_lat,
                "min": min_lat,
                "p50": p50_lat,
                "p90": p90_lat,
                "p95": p95_lat,
                "p99": p99_lat,
                "max": max_lat,
            },
            "backend_distribution": dict(backend_counter),
        }
        with open(args.output_json, "w") as f:
            json.dump(result_data, f, indent=2)
        print(f"[saved] Metrics successfully written to {args.output_json}")


if __name__ == "__main__":
    main()
