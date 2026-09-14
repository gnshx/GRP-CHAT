# Dynamic Performance-Based Load Balancer — Lab 6 Report

**Student:** NUKALA DEVI SAI GANESH | **Roll:** 12341500 | **Score: 12/15 Marks**

**Load Balancer URL:** http://10.1.75.51:5309/ | **Repo:** https://github.com/gnshx/GRP-CHAT

---

## 1. What This Assignment Is About

Deploy the GRP-CHAT application across 3 backend servers, build a Go load balancer in front of them, and ensure:
- All requests are handled under 250–1,000 concurrent users
- GET /feed returns **100% of all messages** (even though they're stored across 3 separate databases)
- Low error rate and fast response times

---

## 2. System Setup

| Machine | Role | Network Address |
|---|---|---|
| Sys 1 | Load Balancer (Go) | 10.1.75.51:5309 ← Submit this |
| Sys 2 | Backend App Server 1 | 10.1.75.51:5310 |
| Sys 3 | Backend App Server 2 | 10.1.75.51:4311 |
| Sys 4 | Backend App Server 3 | 10.1.75.51:3312 |

---

## 3. Official Leaderboard Results

| Stage | Users | Successful | Error Rate | Throughput |
|---|---|---|---|---|
| Stage 1 | 250 | 4,998 / 5,000 | 0.04% | 476.5 req/s |
| Stage 2 | 500 | 4,963 / 5,000 | 0.74% | 200.0 req/s |
| Stage 3 | 750 | 4,783 / 5,000 | 4.32% | 164.8 req/s |
| Stage 4 | 1000 | 4,775 / 5,000 | 4.46% | 164.6 req/s |
| **TOTAL** | **250→1000** | **19,519 / 20,000** | **2.39%** | — |

**Message Completeness: 100.00%** (18,994 / 18,994 found in /feed, 0 lost)
**Content Correctness: 94/100 (94%)**

---

## 4. Unified Feed Aggregation (Key Innovation)

The load balancer's `/feed` handler concurrently queries all 3 backends, merges responses by `msg_id`, sorts by timestamp, caches for 5 seconds, and returns 100% of all accepted messages.

---

## 5. Technical Problems Solved

1. **OOM Kill at Stage 4** → Fixed with `debug.SetMemoryLimit(300MB)` + reduced connection pool
2. **SQLite Lock Contention** → Fixed by making `_invalidate_feed_cache()` a no-op (natural 500ms TTL)
3. **30% Feed Completeness** → Fixed by restoring `handleUnifiedFeed` in loadbalancer.go

---

## 6. Conclusion

Final: 19,519/20,000 requests successful, **100% feed completeness**, 94% content correctness, 2.39% error rate. **Score: 12/15 marks.**
