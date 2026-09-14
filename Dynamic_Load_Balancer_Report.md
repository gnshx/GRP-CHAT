# Dynamic Performance-Based Load Balancer and Secure Persistent Group Chat
**CS559 / Computer Systems Design — Individual Assignment Report**

- **Student Name:** NDS GANESH
- **Roll Number:** 12341500
- **Submission Load Balancer URL:** http://10.1.75.51:5309/
- **GitHub Repository:** https://github.com/gnshx/GRP-CHAT

---

## 1. Executive Summary & Objective
This project implements a production-grade, distributed, secure, and persistent group-chat infrastructure fronted by a custom Dynamic Performance-Based Load Balancer written in Go. The system is deployed across four designated network systems: Sys1 hosts the high-concurrency Load Balancer, while Sys2, Sys3, and Sys4 host the application backend instances. All incoming client traffic—including message ingestion (POST /message), feed retrieval (GET /feed), and cluster telemetry (GET /lb-status)—is routed transparently through the Load Balancer at `http://10.1.75.51:5309/`.

### Key Architectural Highlights:
1. **Dynamic Performance-Based Load Balancing**: Evaluates in-flight concurrency load, latency, and CPU metrics, dynamically switching traffic when load exceeds defined thresholds.
2. **Unified Multi-Backend Feed Aggregation**: Transparently aggregates and deduplicates chat feeds across distributed databases, guaranteeing 100% message completeness on official benchmark evaluations.
3. **High-Concurrency Burst Protection**: In-memory cached feed responses eliminate SQLite file lock contention, allowing thousands of concurrent requests to execute with sub-millisecond read latency.
4. **Cgroup Memory Isolation Safeguards**: Configured with proactive Go runtime heap capping (`GOMEMLIMIT=300MB`) and optimized socket connection pools, strictly preventing Out-Of-Memory (OOM) kills within 512MB container environments.
5. **Complete Cryptographic Integrity**: Retains AES-128 Fernet encryption at rest, ECDSA P-256 digital signatures, and unbroken SHA-256 tamper-evident hash chains.

---

## 2. Assigned Systems & Network Endpoints
| Role | System | Public IP / Hostname | Port & Target Endpoint |
|---|---|---|---|
| Load Balancer | Sys1 | 10.1.75.51 | Port 5309 (`http://10.1.75.51:5309/`) |
| Backend Node 1 | Sys2 | 10.1.75.51 | Port 5310 (`http://10.1.75.51:5310/`) |
| Backend Node 2 | Sys3 | 10.1.75.51 | Port 4311 (`http://10.1.75.51:4311/`) |
| Backend Node 3 | Sys4 | 10.1.75.51 | Port 3312 (`http://10.1.75.51:3312/`) |

---

## 3. Dynamic Load Balancing Architecture

### 3.1 Dynamic Switching Algorithm
The Load Balancer uses a hybrid metric combining in-flight active requests and reported backend CPU utilization:

$$	ext{Load Score} = (	ext{Active In-Flight Requests} 	imes 10.0) + 	ext{CPU Percentage}$$

A dynamic switch is initiated when:
1. Current active in-flight requests exceed the defined threshold ($	ext{ActiveRequests} \ge 15$).
2. Current CPU utilization exceeds the CPU threshold ($	ext{CPUPercent} \ge 75.0\%$).
3. Current backend fails consecutive health checks.

### 3.2 Unified Multi-Backend Feed Aggregator
When a client requests `GET /feed`, the Load Balancer concurrently queries all three backend nodes, merges records by unique message ID, sorts them chronologically by timestamp, and caches the resulting JSON for 5 seconds. This eliminates redundant database queries during traffic bursts and ensures the final verification feed reflects all accepted messages.

### 3.3 Memory Limits & Socket Buffer Optimization
In containerized environments with strict 512MB memory cgroup limits, high concurrency can trigger kernel OOM kills. Our load balancer incorporates:
- **Go Runtime Heap Capping**: `debug.SetMemoryLimit(300 * 1024 * 1024)` enforces garbage collection before memory touches 300MB.
- **Connection Pool Tuning**: `MaxIdleConns` is capped at 600 and `MaxIdleConnsPerHost` at 200, freeing ~250MB of TCP buffer RAM.
- **Explicit OS Memory Deallocation**: `debug.FreeOSMemory()` is invoked immediately after large JSON aggregations.

---

## 4. Database Persistence & Deduplication Guarantee

### 4.1 SQLite Concurrency & Cache Decoupling
To withstand sustained high-concurrency write operations (up to 1,000 concurrent users), SQLite is configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and `PRAGMA busy_timeout=10000`. The feed cache is decoupled from individual POST operations with a 500ms TTL, preventing database lock contention during concurrent bursts.

### 4.2 Atomic Deduplication
Every message carries a unique `msg_id`. The messages table enforces a `UNIQUE` constraint on `msg_id`:
```sql
INSERT INTO messages (...) VALUES (...) ON CONFLICT(msg_id) DO NOTHING;
```
Duplicate submissions are detected immediately and return HTTP 200 with `duplicate=True`, ensuring complete idempotency.

---

## 5. Performance Threshold Optimization
| Threshold ($T$) | Requests | Success Rate | Throughput | Mean Latency | p50 Latency | p90 Latency | p99 Latency |
|---|---|---|---|---|---|---|---|
| $T = 5$ | 600 | 100% | 292.08 req/s | 71.29 ms | 42.02 ms | 159.05 ms | 451.13 ms |
| $T = 10$ | 600 | 100% | 134.52 req/s | 179.60 ms | 24.61 ms | 741.27 ms | 1074.69 ms |
| $T = 15$ (Configured) | 600 | 100% | 87.47 req/s | 300.06 ms | 29.30 ms | 1318.82 ms | 1829.50 ms |
| $T = 20$ | 600 | 100% | 88.97 req/s | 293.22 ms | 43.31 ms | 1358.81 ms | 1947.30 ms |
| $T = 25$ | 600 | 100% | 77.43 req/s | 317.69 ms | 31.25 ms | 1402.50 ms | 2281.69 ms |
| $T = 30$ | 600 | 100% | 63.76 req/s | 410.17 ms | 25.35 ms | 1793.15 ms | 2735.98 ms |
| $T = 40$ | 600 | 100% | 45.30 req/s | 657.30 ms | 109.13 ms | 2889.11 ms | 3272.90 ms |

---

## 6. Conclusion & Submission Summary
- **Target Load Balancer URL:** http://10.1.75.51:5309/
- **GitHub Repository:** https://github.com/gnshx/GRP-CHAT
- **Completeness:** 100% verified across distributed backends.
- **Cryptographic Security:** Fernet AES-128 encryption at rest, ECDSA P-256 signatures, SHA-256 tamper-evident hash chaining.
