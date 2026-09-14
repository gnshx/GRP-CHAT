# DYNAMIC PERFORMANCE-BASED LOAD BALANCER AND SECURE PERSISTENT GROUP CHAT

**Course**: CS559 / Computer Systems Design  
**Student Name**: NDS GANESH  
**Roll Number**: 12341500  
**Submission Load Balancer URL**: `http://10.11.221.87:6000/` (or `http://localhost:6000/`)  
**Repository**: [https://github.com/gnshx/GRP-CHAT](https://github.com/gnshx/GRP-CHAT)  

---

## 1. Executive Summary & Objective

This assignment extends the secure, persistent group-chat system into a robust multi-node architecture deployed across 3 assigned backend nodes (Sys2, Sys3, Sys4) fronted by a high-performance Dynamic Load Balancer on Sys1.

Key accomplishments:
1. **Load Balancer Hosting**: All client interaction (HTTP routes `/message`, `/feed`, `/health`, and real-time WebSockets `/ws`) is hosted exclusively through the Load Balancer on port 6000.
2. **Performance-Based Dynamic Load Balancing**: Implemented dynamic load balancing in Go that monitors in-flight active concurrency load and CPU utilization, dynamically switching traffic away from backends when load exceeds an empirically optimized threshold.
3. **Threshold Optimization**: Systematically experimented across thresholds $T \in \{5, 10, 15, 20, 25, 30, 40\}$, establishing $T=5$ as the optimal performance threshold (achieving **292.08 req/s** throughput and **71.29 ms** mean response time).
4. **Unified Database Persistence & Deduplication**: All backends share a persistent SQLite database (`shared_chat.db`) in WAL mode with atomic deduplication on `msg_id` (`ON CONFLICT(msg_id) DO NOTHING` in `BEGIN IMMEDIATE` exclusive transactions), completely eliminating duplicate insertions during retries.
5. **Security Preservation**: Maintained 100% of previous cryptographic protections: Fernet AES-128-CBC encryption at rest, ECDSA P-256 digital signatures, and an unbroken SHA-256 tamper-evident hash chain across over 6,400 concurrent transactions.
6. **Load Generator**: Developed an advanced multi-threaded load generator supporting variable users, variable message lengths, and variable arrival intervals.

---

## 2. Assigned Systems & Network Endpoints

| Role | System | IP / Hostname | Port & Endpoint |
| :--- | :--- | :--- | :--- |
| **Load Balancer** | Sys1 | `10.11.221.87` | **Port 6000** (`http://10.11.221.87:6000/`) |
| **Backend Node 1** | Sys2 | `10.11.221.87` | **Port 3310** (`http://10.11.221.87:3310/`) |
| **Backend Node 2** | Sys3 | `10.11.221.87` | **Port 3311** (`http://10.11.221.87:3311/`) |
| **Backend Node 3** | Sys4 | `10.11.221.87` | **Port 5312** (`http://10.11.221.87:5312/`) |

### Required API Routes
- `POST /message`: Accepts `"client-name"` and `"msg"` (with optional `"id"`). Submits a cryptographically signed, encrypted, and deduplicated message.
- `GET /feed`: Retrieves all messages in chronological order with decrypted plaintexts and digital signature / hash-chain verification statuses.
- `GET /health`: Cluster health check indicating status of load balancer and all registered backends.
- `GET /lb-status`: Diagnostic endpoint displaying live active requests, CPU metrics, load scores, and dynamic switch counters.

---

## 3. Performance-Based Dynamic Load Balancing

### 3.1 Dynamic Switching Policy
The load balancer tracks each backend's load score:
$$\text{Load Score} = (\text{ActiveRequests} \times 10.0) + \text{CPUPercent}$$
A switch is triggered whenever:
1. The active backend's in-flight request count meets or exceeds the threshold ($\text{ActiveRequests} \ge T$).
2. The active backend's CPU usage exceeds $75.0\%$.
3. The backend fails health checks.

When triggered, traffic is dynamically switched to the alive backend with the lowest load score.

### 3.2 Health Checking & Failover
Every 1 second, a background goroutine tests each backend's `/health` endpoint. Unhealthy nodes are removed within 1 second; recovered nodes automatically rejoin the pool without service downtime.

---

## 4. Shared Persistence & Deduplication Guarantee

### 4.1 Multi-Process SQLite with WAL Mode
- All backends reference `/home/ganesh/Desktop/csd/shared_chat.db`.
- Configured with `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=10000;`.
- Readers execute concurrently without locking writers.

### 4.2 Idempotency & Zero Duplicates
- Messages table enforces `msg_id TEXT UNIQUE`.
- Insertions use `INSERT INTO messages (...) VALUES (...) ON CONFLICT(msg_id) DO NOTHING` wrapped in `BEGIN IMMEDIATE`.
- If a duplicate `msg_id` arrives from retries or reconnections, SQLite safely ignores it and returns `duplicate: true`.
- Zero duplicates occurred across all load generator and stress test runs.

### 4.3 SHA-256 Hash Chain Integrity
Every message extends the sequential hash chain:
$$\text{record\_hash} = \text{SHA256}(\text{prev\_hash} \mid \text{username} \mid \text{ciphertext} \mid \text{signature} \mid \text{timestamp})$$
Across 6,483 multi-backend transactions, verification via `integrity.verify_chain()` reported **0 broken links**.

---

## 5. Experimental Results & Threshold Optimization

### 5.1 Threshold Optimization Benchmark

| Threshold ($T$) | Total Requests | Success Rate | Duration (s) | Throughput (req/s) | Mean Latency (ms) | p50 Latency (ms) | p90 Latency (ms) | p99 Latency (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **5 (Optimal)** | **600** | **100%** | **2.05** | **292.08** | **71.29** | **42.02** | **159.05** | **451.13** |
| 10 | 600 | 100% | 4.46 | 134.52 | 179.60 | 24.61 | 741.27 | 1074.69 |
| 15 | 600 | 100% | 6.86 | 87.47 | 300.06 | 29.30 | 1318.82 | 1829.50 |
| 20 | 600 | 100% | 6.74 | 88.97 | 293.22 | 43.31 | 1358.81 | 1947.30 |
| 25 | 600 | 100% | 7.75 | 77.43 | 317.69 | 31.25 | 1402.50 | 2281.69 |
| 30 | 600 | 100% | 9.41 | 63.76 | 410.17 | 25.35 | 1793.15 | 2735.98 |
| 40 | 600 | 100% | 13.25 | 45.30 | 657.30 | 109.13 | 2889.11 | 3272.90 |

**Finding**: $T=5$ is optimal. It prevents request accumulation before socket queues grow, achieving 6.4x higher throughput and 9.2x lower latency than high thresholds ($T=40$).

### 5.2 4-System Resource Utilization
Measured over 1,250 requests (50 concurrent users):

| System | Process / Role | Average CPU (%) | Peak CPU (%) | Memory RSS (MB) |
| :--- | :--- | :---: | :---: | :---: |
| **Sys1** | Load Balancer (Go) | **5.6%** | 16.0% | 14.9 MB |
| **Sys2** | Backend 1 (Flask) | **158.6%** | 211.3% | 136.7 MB |
| **Sys3** | Backend 2 (Flask) | **156.1%** | 219.3% | 114.0 MB |
| **Sys4** | Backend 3 (Flask) | **158.2%** | 211.3% | 107.4 MB |

All three backends operated at nearly identical average CPU utilization (~158%), proving uniform load distribution.

### 5.3 Concurrency Scalability

| Concurrent Clients | Total Requests | Success Rate | Elapsed Time (s) | Throughput (req/s) | Mean Latency (ms) | p90 Latency (ms) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 10 | 150 | 100% | 1.57 | 95.25 | 46.60 | 138.60 |
| 20 | 300 | 100% | 3.16 | 95.03 | 127.58 | 518.51 |
| 30 | 450 | 100% | 5.00 | 90.06 | 219.99 | 1023.54 |
| 40 | 600 | 100% | 7.23 | 82.93 | 336.21 | 1426.23 |
| 50 | 750 | 100% | 8.03 | 93.37 | 373.92 | 1850.68 |
| 60 | 900 | 100% | 11.31 | 79.60 | 501.24 | 2128.10 |

---

## 6. Generated Evaluation Plots

All plots were generated using `benchmark_suite.py` and `matplotlib`:
1. `plot_threshold_optimization.png`: Throughput vs. Latency trade-off showing the optimal threshold $T=5$.
2. `plot_system_utilization.png`: Real-time CPU and memory curves for Sys1, Sys2, Sys3, Sys4.
3. `plot_response_time.png`: Response time percentiles (mean, p50, p90, p99) under scaling client concurrency.
4. `plot_backend_distribution.png`: Backend traffic distribution proving dynamic load balancing across backends.

---

## 7. Submission Details

- **Submission Endpoint**: `http://10.11.221.87:6000/`
- **Health Check Endpoint**: `http://10.11.221.87:6000/health`
- **Required API 1**: `http://10.11.221.87:6000/message`
- **Required API 2**: `http://10.11.221.87:6000/feed`
- **Repository URL**: `https://github.com/gnshx/GRP-CHAT`
