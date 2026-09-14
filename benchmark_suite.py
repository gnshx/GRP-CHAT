#!/usr/bin/env python3
"""
Comprehensive Benchmark & Evaluation Suite for GRP-CHAT Dynamic Load Balancing
Conducts experiments, optimizes performance threshold, tracks 4-system utilization,
and generates all evaluation plots for the assignment report.
"""

import json
import os
import subprocess
import sys
import time
import matplotlib.pyplot as plt
import numpy as np
from monitor import SystemMonitor

LB_PORT = 6000
SYS2_PORT = 3310
SYS3_PORT = 3311
SYS4_PORT = 5312
BASE_URL = f"http://127.0.0.1:{LB_PORT}"

PYTHON_SYS1 = "/home/ganesh/Desktop/csd/sys-1/GRP-CHAT/.venv/bin/python3"
PYTHON_SYS2 = "/home/ganesh/Desktop/csd/sys-2/GRP-CHAT/.venv/bin/python3"
PYTHON_SYS3 = "/home/ganesh/Desktop/csd/sys-3/GRP-CHAT/.venv/bin/python3"
PYTHON_SYS4 = "/home/ganesh/Desktop/csd/sys-4/GRP-CHAT/.venv/bin/python3"

OUTPUT_DIR = "/home/ganesh/Desktop/csd/benchmark_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def stop_process_on_port(port: int):
    try:
        cmd = f"lsof -ti:{port} | xargs -r kill -9"
        subprocess.run(cmd, shell=True, check=False)
    except Exception:
        pass


def stop_all():
    print("[suite] Stopping any existing instances on ports 6000, 3310, 3311, 5312...")
    for p in [LB_PORT, SYS2_PORT, SYS3_PORT, SYS4_PORT]:
        stop_process_on_port(p)
    time.sleep(1.0)


def start_backend(sys_num: int, port: int, py_path: str):
    cwd = f"/home/ganesh/Desktop/csd/sys-{sys_num}/GRP-CHAT"
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["CHAT_DB_PATH"] = "/home/ganesh/Desktop/csd/shared_chat.db"
    env["CHAT_SECRET_FILE"] = "/home/ganesh/Desktop/csd/secret.key"
    cmd = [py_path, "app.py", f"--port={port}"]
    log_file = open(f"{OUTPUT_DIR}/sys{sys_num}.log", "w")
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log_file, stderr=log_file)
    print(f"[suite] Started Sys{sys_num} Backend on port {port} (PID: {proc.pid})")
    return proc


def start_load_balancer(threshold: int = 15, cpu_threshold: float = 75.0):
    cwd = "/home/ganesh/Desktop/csd/sys-1/GRP-CHAT"
    backends = f"http://127.0.0.1:{SYS2_PORT},http://127.0.0.1:{SYS3_PORT},http://127.0.0.1:{SYS4_PORT}"
    cmd = [
        "go", "run", "loadbalancer.go",
        f"-backends={backends}",
        f"-port={LB_PORT}",
        f"-threshold={threshold}",
        f"-cpu-threshold={cpu_threshold}",
        "-health-interval=1s",
        "-poll-interval=500ms"
    ]
    log_file = open(f"{OUTPUT_DIR}/lb.log", "w")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=log_file, stderr=log_file)
    print(f"[suite] Started Load Balancer on port {LB_PORT} (Threshold={threshold}, PID: {proc.pid})")
    time.sleep(2.0)
    return proc


def wait_for_ready(url: str, timeout: float = 10.0):
    import requests
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{url}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def run_single_load_test(users: int, reqs_per_user: int, output_json: str):
    cmd = [
        PYTHON_SYS1, "/home/ganesh/Desktop/csd/sys-1/GRP-CHAT/load_generator.py",
        f"--url={BASE_URL}",
        f"--users={users}",
        f"--requests-per-user={reqs_per_user}",
        "--min-len=15",
        "--max-len=150",
        "--min-interval=0.01",
        "--max-interval=0.06",
        "--feed-ratio=0.25",
        f"--output-json={output_json}"
    ]
    subprocess.run(cmd, check=True)
    with open(output_json, "r") as f:
        return json.load(f)


def experiment_threshold_optimization():
    print("\n" + "=" * 60)
    print("EXPERIMENT 1: THRESHOLD OPTIMIZATION")
    print("=" * 60)

    thresholds = [5, 10, 15, 20, 25, 30, 40]
    results = []

    for t in thresholds:
        print(f"\n--- Testing Threshold = {t} ---")
        stop_process_on_port(LB_PORT)
        time.sleep(1.0)
        lb_proc = start_load_balancer(threshold=t)
        if not wait_for_ready(BASE_URL):
            print(f"[error] Load Balancer failed to ready for threshold {t}")
            continue

        out_file = f"{OUTPUT_DIR}/threshold_{t}.json"
        res = run_single_load_test(users=40, reqs_per_user=15, output_json=out_file)
        res["threshold"] = t
        results.append(res)
        time.sleep(1.0)

    # Save summary
    with open(f"{OUTPUT_DIR}/threshold_optimization_summary.json", "w") as f:
        json.dump(results, f, indent=2)

    return results


def experiment_system_utilization(optimal_threshold: int):
    print("\n" + "=" * 60)
    print("EXPERIMENT 2: 4-SYSTEM UTILIZATION PROFILING")
    print("=" * 60)

    stop_process_on_port(LB_PORT)
    time.sleep(1.0)
    lb_proc = start_load_balancer(threshold=optimal_threshold)
    wait_for_ready(BASE_URL)

    monitor = SystemMonitor(interval=0.25)
    monitor.start()

    time.sleep(1.0)
    print("[suite] Running heavy workload to measure utilization curves...")
    out_file = f"{OUTPUT_DIR}/high_load_run.json"
    run_single_load_test(users=50, reqs_per_user=25, output_json=out_file)

    time.sleep(1.0)
    records = monitor.stop(f"{OUTPUT_DIR}/system_utilization.json")
    return records


def experiment_concurrency_scaling(optimal_threshold: int):
    print("\n" + "=" * 60)
    print("EXPERIMENT 3: CONCURRENCY SCALING & RESPONSE TIME")
    print("=" * 60)

    concurrency_levels = [10, 20, 30, 40, 50, 60]
    results = []

    for c in concurrency_levels:
        print(f"\n--- Testing Concurrency Users = {c} ---")
        out_file = f"{OUTPUT_DIR}/concurrency_{c}.json"
        res = run_single_load_test(users=c, reqs_per_user=15, output_json=out_file)
        res["concurrency"] = c
        results.append(res)
        time.sleep(0.5)

    with open(f"{OUTPUT_DIR}/concurrency_summary.json", "w") as f:
        json.dump(results, f, indent=2)

    return results


def generate_plots(threshold_results, utilization_records, concurrency_results, optimal_threshold: int):
    print("\n" + "=" * 60)
    print("GENERATING PUBLICATION PLOTS")
    print("=" * 60)

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")

    # Plot 1: Threshold Optimization (Throughput & Latency vs Threshold)
    fig, ax1 = plt.subplots(figsize=(10, 6))
    thresholds = [r["threshold"] for r in threshold_results]
    throughputs = [r["throughput_rps"] for r in threshold_results]
    latencies = [r["latency_ms"]["mean"] for r in threshold_results]
    p90_latencies = [r["latency_ms"]["p90"] for r in threshold_results]

    color = "#1f77b4"
    ax1.set_xlabel("Dynamic Load Balancing Threshold (Active In-Flight Reqs)", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Throughput (Requests / sec)", color=color, fontsize=12, fontweight="bold")
    line1 = ax1.plot(thresholds, throughputs, color=color, marker="o", linewidth=2.5, label="Throughput (req/s)")
    ax1.tick_params(axis="y", labelcolor=color)

    ax2 = ax1.twinx()
    color = "#d62728"
    ax2.set_ylabel("Response Time (ms)", color=color, fontsize=12, fontweight="bold")
    line2 = ax2.plot(thresholds, latencies, color=color, marker="s", linewidth=2.5, linestyle="--", label="Mean Latency (ms)")
    line3 = ax2.plot(thresholds, p90_latencies, color="#ff7f0e", marker="^", linewidth=2.0, linestyle=":", label="p90 Latency (ms)")
    ax2.tick_params(axis="y", labelcolor=color)

    # Highlight optimal threshold
    ax1.axvline(x=optimal_threshold, color="#2ca02c", linestyle="-.", linewidth=2, label=f"Optimal Threshold (T={optimal_threshold})")

    lines = line1 + line2 + line3 + [plt.Line2D([0], [0], color="#2ca02c", linestyle="-.", linewidth=2, label=f"Optimal Threshold (T={optimal_threshold})")]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="center right", frameon=True, shadow=True)

    plt.title("Performance Threshold Optimization: Throughput & Latency Trade-Off", fontsize=14, fontweight="bold", pad=15)
    plt.tight_layout()
    p1 = f"{OUTPUT_DIR}/plot_threshold_optimization.png"
    plt.savefig(p1, dpi=300)
    plt.close()
    print(f"[plot] Saved {p1}")

    # Plot 2: 4-System Utilization (CPU & Memory over time for Sys1, Sys2, Sys3, Sys4)
    if utilization_records:
        times = [r["time_sec"] for r in utilization_records]
        fig, (ax_cpu, ax_mem) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

        colors = {
            "Sys1_LB": "#3366cc",
            "Sys2_Backend1": "#dc3912",
            "Sys3_Backend2": "#ff9900",
            "Sys4_Backend3": "#109618",
        }
        labels = {
            "Sys1_LB": "Sys1 (Load Balancer)",
            "Sys2_Backend1": "Sys2 (Backend 1 - Port 3310)",
            "Sys3_Backend2": "Sys3 (Backend 2 - Port 3311)",
            "Sys4_Backend3": "Sys4 (Backend 3 - Port 5312)",
        }

        for k in ["Sys1_LB", "Sys2_Backend1", "Sys3_Backend2", "Sys4_Backend3"]:
            cpu_vals = [r.get(f"{k}_cpu", 0.0) for r in utilization_records]
            mem_vals = [r.get(f"{k}_mem_mb", 0.0) for r in utilization_records]
            ax_cpu.plot(times, cpu_vals, label=labels[k], color=colors[k], linewidth=2.0)
            ax_mem.plot(times, mem_vals, label=labels[k], color=colors[k], linewidth=2.0)

        ax_cpu.set_ylabel("CPU Utilization (%)", fontsize=11, fontweight="bold")
        ax_cpu.set_title("System Resource Utilization Across All 4 Systems During Load Test", fontsize=13, fontweight="bold")
        ax_cpu.legend(loc="upper right", frameon=True)
        ax_cpu.set_ylim(bottom=0)

        ax_mem.set_xlabel("Elapsed Time (seconds)", fontsize=11, fontweight="bold")
        ax_mem.set_ylabel("Memory RSS (MB)", fontsize=11, fontweight="bold")
        ax_mem.legend(loc="upper right", frameon=True)
        ax_mem.set_ylim(bottom=0)

        plt.tight_layout()
        p2 = f"{OUTPUT_DIR}/plot_system_utilization.png"
        plt.savefig(p2, dpi=300)
        plt.close()
        print(f"[plot] Saved {p2}")

    # Plot 3: Response Time vs Concurrency (Mean, p50, p90, p99)
    if concurrency_results:
        fig, ax = plt.subplots(figsize=(10, 6))
        users = [r["concurrency"] for r in concurrency_results]
        means = [r["latency_ms"]["mean"] for r in concurrency_results]
        p50s = [r["latency_ms"]["p50"] for r in concurrency_results]
        p90s = [r["latency_ms"]["p90"] for r in concurrency_results]
        p99s = [r["latency_ms"]["p99"] for r in concurrency_results]

        ax.plot(users, means, marker="o", linewidth=2.5, color="#1f77b4", label="Mean Response Time")
        ax.plot(users, p50s, marker="s", linewidth=2.0, linestyle="--", color="#2ca02c", label="p50 (Median)")
        ax.plot(users, p90s, marker="^", linewidth=2.0, linestyle="-.", color="#ff7f0e", label="p90 Latency")
        ax.plot(users, p99s, marker="d", linewidth=2.0, linestyle=":", color="#d62728", label="p99 Latency")

        ax.set_xlabel("Concurrent Client Count", fontsize=12, fontweight="bold")
        ax.set_ylabel("Response Time (ms)", fontsize=12, fontweight="bold")
        ax.set_title("Response Time Scalability Under Dynamic Load Balancing", fontsize=14, fontweight="bold", pad=15)
        ax.legend(loc="upper left", frameon=True, shadow=True)
        plt.tight_layout()
        p3 = f"{OUTPUT_DIR}/plot_response_time.png"
        plt.savefig(p3, dpi=300)
        plt.close()
        print(f"[plot] Saved {p3}")

    # Plot 4: Backend Distribution (Proof of Dynamic Load Balancing)
    # Find test result at optimal threshold
    opt_res = next((r for r in threshold_results if r["threshold"] == optimal_threshold), threshold_results[0])
    dist = opt_res.get("backend_distribution", {})
    if dist:
        fig, ax = plt.subplots(figsize=(8, 5))
        backends = list(dist.keys())
        counts = list(dist.values())
        total = sum(counts)
        pcts = [(c / total) * 100 for c in counts]
        bars = ax.bar(backends, counts, color=["#4285F4", "#EA4335", "#FBBC05"], width=0.5, edgecolor="black", linewidth=1.2)

        for bar, pct, count in zip(bars, pcts, counts):
            height = bar.get_height()
            ax.annotate(f"{count} reqs\n({pct:.1f}%)",
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", fontsize=11, fontweight="bold")

        ax.set_ylabel("Requests Processed", fontsize=12, fontweight="bold")
        ax.set_title("Traffic Distribution Across 3 Backends (Proof of Dynamic Balancing)", fontsize=13, fontweight="bold", pad=15)
        ax.set_ylim(0, max(counts) * 1.25)
        plt.tight_layout()
        p4 = f"{OUTPUT_DIR}/plot_backend_distribution.png"
        plt.savefig(p4, dpi=300)
        plt.close()
        print(f"[plot] Saved {p4}")


def main():
    stop_all()

    # Clean previous shared db to start fresh benchmark
    import glob
    for f in glob.glob("/home/ganesh/Desktop/csd/shared_chat.db*"):
        try:
            os.remove(f)
        except Exception:
            pass

    # Start 3 backends
    b1 = start_backend(2, SYS2_PORT, PYTHON_SYS2)
    b2 = start_backend(3, SYS3_PORT, PYTHON_SYS3)
    b3 = start_backend(4, SYS4_PORT, PYTHON_SYS4)

    time.sleep(3.0)
    for p in [SYS2_PORT, SYS3_PORT, SYS4_PORT]:
        if not wait_for_ready(f"http://127.0.0.1:{p}"):
            print(f"[error] Backend on port {p} not ready!")
            return

    # Verify Deduplication via Load Generator first
    lb_proc = start_load_balancer(threshold=15)
    wait_for_ready(BASE_URL)
    from load_generator import run_dedup_test
    dedup_ok = run_dedup_test(BASE_URL)
    print(f"[suite] Deduplication verified: {dedup_ok}")

    # 1. Threshold Optimization
    threshold_results = experiment_threshold_optimization()

    # Determine optimal threshold: minimize (Latency / Throughput) trade-off
    scored = []
    for r in threshold_results:
        t = r["threshold"]
        tps = r["throughput_rps"]
        lat = r["latency_ms"]["p90"]
        # Efficiency metric: Throughput per ms of p90 latency
        score = tps / (lat if lat > 0 else 1.0)
        scored.append((score, t, r))
    scored.sort(reverse=True)
    optimal_threshold = scored[0][1]
    print(f"\n>>> DETERMINED OPTIMAL THRESHOLD: T = {optimal_threshold} (Score: {scored[0][0]:.3f}) <<<")

    # 2. 4-System Utilization with optimal threshold
    utilization_records = experiment_system_utilization(optimal_threshold)

    # 3. Concurrency Scalability
    concurrency_results = experiment_concurrency_scaling(optimal_threshold)

    # 4. Generate all plots
    generate_plots(threshold_results, utilization_records, concurrency_results, optimal_threshold)

    # Final persistent setup: Leave Load Balancer running at optimal threshold
    stop_process_on_port(LB_PORT)
    time.sleep(1.0)
    final_lb = start_load_balancer(threshold=optimal_threshold)
    print(f"\n[suite] Benchmark Suite Complete! Dynamic Load Balancer actively serving on port {LB_PORT}")


if __name__ == "__main__":
    main()
