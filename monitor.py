#!/usr/bin/env python3
"""
System Utilization Monitor for all 4 systems:
  - Sys1: Load Balancer (Port 6000)
  - Sys2: Backend 1     (Port 3310)
  - Sys3: Backend 2     (Port 3311)
  - Sys4: Backend 3     (Port 5312)

Tracks CPU % and Memory utilization over time during load generator runs.
"""

import json
import os
import sys
import threading
import time
import psutil

PORTS = {
    "Sys1_LB": 6000,
    "Sys2_Backend1": 3310,
    "Sys3_Backend2": 3311,
    "Sys4_Backend3": 5312,
}


def find_pid_by_port(port: int):
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
            return conn.pid
    return None


class SystemMonitor:
    def __init__(self, interval: float = 0.25):
        self.interval = interval
        self.running = False
        self.thread = None
        self.records = []
        self.proc_map = {}

    def discover_processes(self):
        for name, port in PORTS.items():
            pid = find_pid_by_port(port)
            if pid:
                try:
                    proc = psutil.Process(pid)
                    # prime cpu_percent
                    proc.cpu_percent(interval=None)
                    self.proc_map[name] = proc
                    print(f"[monitor] Found {name} (PID: {pid}, Port: {port})")
                except Exception as e:
                    print(f"[monitor] Error attaching to {name} PID {pid}: {e}")
            else:
                print(f"[monitor] Warning: {name} not found on Port {port}")

    def _loop(self):
        start_time = time.time()
        while self.running:
            now = time.time() - start_time
            point = {"time_sec": round(now, 2)}

            for name, proc in self.proc_map.items():
                try:
                    if proc.is_running():
                        cpu = proc.cpu_percent(interval=None)
                        mem = proc.memory_percent()
                        mem_mb = proc.memory_info().rss / (1024 * 1024)
                        point[f"{name}_cpu"] = round(cpu, 1)
                        point[f"{name}_mem_mb"] = round(mem_mb, 1)
                        point[f"{name}_mem_pct"] = round(mem, 1)
                    else:
                        point[f"{name}_cpu"] = 0.0
                        point[f"{name}_mem_mb"] = 0.0
                except Exception:
                    point[f"{name}_cpu"] = 0.0
                    point[f"{name}_mem_mb"] = 0.0

            point["host_cpu_pct"] = round(psutil.cpu_percent(interval=None), 1)
            self.records.append(point)
            time.sleep(self.interval)

    def start(self):
        self.discover_processes()
        self.running = True
        self.records = []
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[monitor] Background monitoring started.")

    def stop(self, output_file: str = "system_utilization.json"):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        print(f"[monitor] Monitoring stopped. Captured {len(self.records)} samples.")
        with open(output_file, "w") as f:
            json.dump(self.records, f, indent=2)
        print(f"[monitor] Saved utilization records to {output_file}")
        return self.records


if __name__ == "__main__":
    monitor = SystemMonitor(interval=0.5)
    monitor.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop("test_utilization.json")
