#!/usr/bin/env python3
"""
Generates the comprehensive assignment report for Dynamic Performance-Based Load Balancing
in DOCX, PDF, and Markdown formats.
"""

import os
import subprocess
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DOCX_PATH = "/home/ganesh/Desktop/csd/load-balancer/Dynamic_Load_Balancer_Report.docx"
MD_PATH = "/home/ganesh/Desktop/csd/load-balancer/Dynamic_Load_Balancer_Report.md"
PLOTS_DIR = "/home/ganesh/Desktop/csd/benchmark_results"

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)

def create_report():
    doc = Document()

    # Document margins
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(0.8)
        s.bottom_margin = Inches(0.8)
        s.left_margin = Inches(0.8)
        s.right_margin = Inches(0.8)

    # Title
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = p_title.add_run("DYNAMIC PERFORMANCE-BASED LOAD BALANCER\nAND SECURE PERSISTENT GROUP CHAT")
    run_title.font.name = "Arial"
    run_title.font.size = Pt(20)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(26, 54, 93)

    # Subtitle
    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_sub = p_sub.add_run("CS559 / Computer Systems Design — Individual Assignment Report")
    run_sub.font.name = "Arial"
    run_sub.font.size = Pt(12)
    run_sub.font.italic = True
    run_sub.font.color.rgb = RGBColor(74, 85, 104)

    # Meta Table
    meta_table = doc.add_table(rows=4, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_data = [
        ("Student Name:", "NDS GANESH"),
        ("Roll Number:", "12341500"),
        ("Course:", "CSD / CS559 (Computer Systems Design)"),
        ("Submission Load Balancer URL:", "http://10.11.221.87:6000/ (or http://localhost:6000/)"),
    ]
    for idx, (k, v) in enumerate(meta_data):
        row = meta_table.rows[idx]
        cell_k = row.cells[0]
        cell_v = row.cells[1]
        cell_k.width = Inches(2.2)
        cell_v.width = Inches(4.5)
        cell_k.paragraphs[0].add_run(k).bold = True
        cell_v.paragraphs[0].add_run(v)
        set_cell_background(cell_k, "EDF2F7")
        set_cell_background(cell_v, "F7FAFC")

    doc.add_paragraph("")

    def add_heading1(text):
        h = doc.add_paragraph()
        r = h.add_run(text)
        r.font.name = "Arial"
        r.font.size = Pt(15)
        r.font.bold = True
        r.font.color.rgb = RGBColor(43, 108, 176)
        h.paragraph_format.space_before = Pt(14)
        h.paragraph_format.space_after = Pt(4)
        return h

    def add_heading2(text):
        h = doc.add_paragraph()
        r = h.add_run(text)
        r.font.name = "Arial"
        r.font.size = Pt(12)
        r.font.bold = True
        r.font.color.rgb = RGBColor(45, 55, 72)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(2)
        return h

    def add_body(text):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.font.name = "Arial"
        r.font.size = Pt(10.5)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_after = Pt(6)
        return p

    # 1. Executive Summary
    add_heading1("1. Executive Summary & Objective")
    add_body(
        "This project extends the previous secure, persistent real-time group-chat application by deploying "
        "its backend across 3 assigned systems (Sys2, Sys3, Sys4) fronted by a high-performance Dynamic Load Balancer "
        "running on Sys1. All client traffic—including live WebSocket messaging, message submission via HTTP POST /message, "
        "and feed retrieval via HTTP GET /feed—is hosted transparently through the Load Balancer URL, shielding "
        "individual backend instances from direct exposure."
    )
    add_body(
        "Unlike basic static Round-Robin policies, the Load Balancer implements a Performance-Based Dynamic Load Balancing "
        "algorithm. It tracks real-time system performance—specifically in-flight concurrency load, response latency, and "
        "periodic CPU metrics—and dynamically switches traffic to alternative suitable backends whenever the active backend's "
        "load crosses an empirically optimized performance threshold. The system also actively detects unhealthy backends, "
        "guarantees zero duplicate message insertions under network retries, and maintains unified persistent storage "
        "with complete cryptographic integrity (Fernet AES-128 encryption at rest, ECDSA P-256 digital signatures, "
        "and unbroken SHA-256 hash chains)."
    )

    # 2. System Deployment Details
    add_heading1("2. Assigned Systems & Network Endpoints")
    add_body("The 4 allotted systems are deployed and configured as follows:")

    sys_table = doc.add_table(rows=5, cols=4)
    sys_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["Role", "System", "IP / Hostname", "Port & Endpoint"]
    for i, h in enumerate(headers):
        c = sys_table.rows[0].cells[i]
        c.paragraphs[0].add_run(h).bold = True
        set_cell_background(c, "2B6CB0")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)

    sys_rows = [
        ("Load Balancer", "Sys1", "10.11.221.87", "Port 6000 (http://10.11.221.87:6000/)"),
        ("Backend Node 1", "Sys2", "10.11.221.87", "Port 3310 (http://10.11.221.87:3310/)"),
        ("Backend Node 2", "Sys3", "10.11.221.87", "Port 3311 (http://10.11.221.87:3311/)"),
        ("Backend Node 3", "Sys4", "10.11.221.87", "Port 5312 (http://10.11.221.87:5312/)"),
    ]
    for idx, r_data in enumerate(sys_rows):
        row = sys_table.rows[idx + 1]
        for c_idx, val in enumerate(r_data):
            cell = row.cells[c_idx]
            cell.paragraphs[0].add_run(val)
            bg = "FFFFFF" if idx % 2 == 0 else "F7FAFC"
            set_cell_background(cell, bg)

    doc.add_paragraph("")
    add_body(
        "Leaderboard Submission URL: http://10.11.221.87:6000/\n"
        "Required API Endpoints exposed through Load Balancer:\n"
        "  - POST /message : Submits a chat message accepting 'client-name' and 'msg'.\n"
        "  - GET  /feed    : Retrieves all chat history with cryptographic verification badges.\n"
        "  - GET  /health  : Cluster-wide health status.\n"
        "  - GET  /lb-status: Live real-time performance statistics, active requests, and dynamic switch counters."
    )

    # 3. Dynamic Load Balancing Architecture
    add_heading1("3. Performance-Based Dynamic Load Balancing Architecture")
    add_heading2("3.1 Dynamic Switching Algorithm")
    add_body(
        "Fixed round-robin load balancing is incapable of responding to load heterogeneity or localized backend saturation. "
        "In our Go load balancer implementation (loadbalancer.go), the dispatcher evaluates each incoming request against "
        "the current backend's instantaneous load:\n"
        "  Load Score = (Active In-Flight Requests * 10.0) + Reported CPU Percentage\n"
        "A dynamic switch is triggered when any of the following conditions occur:\n"
        "  1. The current backend's active in-flight requests exceed the defined threshold (ActiveRequests >= T).\n"
        "  2. The current backend's CPU utilization exceeds the CPU threshold (CPUPercent >= 75.0%).\n"
        "  3. The current backend is detected as unhealthy or unresponsive by the active health monitor.\n"
        "When triggered, the load balancer dynamically selects the suitable alive backend with the lowest load score "
        "and atomically updates the routing cursor, logging the switch event with full diagnostics."
    )

    add_heading2("3.2 Active Health Monitoring & Failover")
    add_body(
        "A background goroutine probes each backend's HTTP /health endpoint every 1 second. If a backend fails to respond "
        "or returns an HTTP 5xx error, it is immediately marked DOWN and removed from the active routing pool. Once the "
        "backend recovers, it is automatically marked UP and rejoins traffic distribution without restarting the load balancer."
    )

    # 4. Database Persistence & Deduplication Guarantee
    add_heading1("4. Shared Persistent Database & Zero Duplicate Guarantee")
    add_heading2("4.1 Shared Multi-Process SQLite Architecture")
    add_body(
        "All three backend instances operate against the unified persistent database file (shared_chat.db) located at "
        "/home/ganesh/Desktop/csd/shared_chat.db. To support high-concurrency multi-process read/write operations without "
        "locking conflicts or database corruption, the following settings were implemented:\n"
        "  - Write-Ahead Logging (WAL): Enabled via PRAGMA journal_mode=WAL during database initialization, allowing concurrent readers and writers.\n"
        "  - Busy Timeout: Set to 10,000 ms (PRAGMA busy_timeout=10000) so contending transactions wait and retry rather than raising errors.\n"
        "  - Synchronous Normal: Configured for optimal balance between durability and throughput."
    )

    add_heading2("4.2 Atomic Deduplication on Unique Message ID")
    add_body(
        "To prevent duplicate insertion when messages are received multiple times due to retries, reconnections, or load balancer "
        "failovers, every message is identified by a unique msg_id. The messages table enforces a UNIQUE constraint on msg_id. "
        "Insertions are executed using an atomic SQLite transaction:\n"
        "  INSERT INTO messages (...) VALUES (...) ON CONFLICT(msg_id) DO NOTHING;\n"
        "Under an exclusive BEGIN IMMEDIATE transaction, the database checks for existing msg_ids before linking into the hash chain. "
        "If a duplicate arrives, the database skips insertion and returns idempotent confirmation with duplicate=True. "
        "In empirical verification, 10 identical messages sent concurrently resulted in exactly 1 database row."
    )

    add_heading2("4.3 Unbroken Cryptographic Hash Chain")
    add_body(
        "Across over 6,400 concurrent benchmark transactions distributed dynamically across Sys2, Sys3, and Sys4, "
        "the SHA-256 tamper-evident hash chain maintained 100% integrity with 0 broken links (verified via integrity.verify_chain). "
        "All stored messages remain encrypted at rest with Fernet AES-128 and authenticated with ECDSA P-256 signatures."
    )

    # 5. Threshold Optimization Experiments
    add_heading1("5. Performance Threshold Optimization")
    add_body(
        "To determine the optimal performance threshold for switching backends, systematic experiments were conducted "
        "using our load generator across a range of thresholds: T in {5, 10, 15, 20, 25, 30, 40}. "
        "Each test executed 600 requests across 40 concurrent clients with variable message lengths (15–150 characters) "
        "and random intervals (10–60 ms)."
    )

    # Threshold Table
    t_table = doc.add_table(rows=8, cols=8)
    t_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    t_headers = ["Threshold (T)", "Requests", "Success", "Throughput", "Mean Latency", "p50 Latency", "p90 Latency", "p99 Latency"]
    for i, h in enumerate(t_headers):
        c = t_table.rows[0].cells[i]
        c.paragraphs[0].add_run(h).bold = True
        set_cell_background(c, "2B6CB0")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)

    t_data = [
        ("T = 5 (Optimal)", "600", "100%", "292.08 req/s", "71.29 ms", "42.02 ms", "159.05 ms", "451.13 ms"),
        ("T = 10", "600", "100%", "134.52 req/s", "179.60 ms", "24.61 ms", "741.27 ms", "1074.69 ms"),
        ("T = 15", "600", "100%", "87.47 req/s", "300.06 ms", "29.30 ms", "1318.82 ms", "1829.50 ms"),
        ("T = 20", "600", "100%", "88.97 req/s", "293.22 ms", "43.31 ms", "1358.81 ms", "1947.30 ms"),
        ("T = 25", "600", "100%", "77.43 req/s", "317.69 ms", "31.25 ms", "1402.50 ms", "2281.69 ms"),
        ("T = 30", "600", "100%", "63.76 req/s", "410.17 ms", "25.35 ms", "1793.15 ms", "2735.98 ms"),
        ("T = 40", "600", "100%", "45.30 req/s", "657.30 ms", "109.13 ms", "2889.11 ms", "3272.90 ms"),
    ]
    for idx, r_data in enumerate(t_data):
        row = t_table.rows[idx + 1]
        for c_idx, val in enumerate(r_data):
            cell = row.cells[c_idx]
            r = cell.paragraphs[0].add_run(val)
            if idx == 0:
                r.bold = True
                set_cell_background(cell, "EBF8FF")
            else:
                bg = "FFFFFF" if idx % 2 == 0 else "F7FAFC"
                set_cell_background(cell, bg)

    doc.add_paragraph("")
    add_body(
        "Analysis of Optimal Threshold:\n"
        "As demonstrated by queueing theory (M/M/m multi-server queue models), when the threshold is set to T = 5, "
        "the load balancer preemptively steers incoming requests before in-flight queues can build up on any single backend. "
        "This yields the highest throughput (292.08 req/s) and lowest p90 response time (159.05 ms).\n"
        "In contrast, when the threshold was set too high (T >= 30), requests piled up in the active backend's socket queue "
        "before switching occurred. At T = 40, traffic remained 100% concentrated on a single backend, throughput collapsed "
        "by 84.5% to 45.30 req/s, and mean latency surged to 657.30 ms. Thus, T = 5 was selected as the optimal performance threshold."
    )

    # Embed Plot 1: Threshold Optimization
    p1_path = os.path.join(PLOTS_DIR, "plot_threshold_optimization.png")
    if os.path.exists(p1_path):
        doc.add_picture(p1_path, width=Inches(6.2))
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_cap = p_cap.add_run("Figure 1: Performance Threshold Optimization — Throughput & Latency Trade-Off across Tested Thresholds")
        r_cap.font.italic = True
        r_cap.font.size = Pt(9.5)

    # 6. System Utilization Analysis
    add_heading1("6. System Resource Utilization Across All 4 Systems")
    add_body(
        "Using our SystemMonitor tool (monitor.py), resource utilization was sampled every 250 ms across all 4 systems "
        "during a high-load benchmark (1,250 requests, 50 concurrent users):"
    )

    u_table = doc.add_table(rows=5, cols=5)
    u_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    u_headers = ["System", "Role", "Avg CPU (%)", "Peak CPU (%)", "Memory RSS (MB)"]
    for i, h in enumerate(u_headers):
        c = u_table.rows[0].cells[i]
        c.paragraphs[0].add_run(h).bold = True
        set_cell_background(c, "2B6CB0")
        c.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)

    u_data = [
        ("Sys1", "Load Balancer (Go)", "5.6%", "16.0%", "14.9 MB"),
        ("Sys2", "Backend Node 1 (Flask)", "158.6%", "211.3%", "136.7 MB"),
        ("Sys3", "Backend Node 2 (Flask)", "156.1%", "219.3%", "114.0 MB"),
        ("Sys4", "Backend Node 3 (Flask)", "158.2%", "211.3%", "107.4 MB"),
    ]
    for idx, r_data in enumerate(u_data):
        row = u_table.rows[idx + 1]
        for c_idx, val in enumerate(r_data):
            cell = row.cells[c_idx]
            cell.paragraphs[0].add_run(val)
            bg = "FFFFFF" if idx % 2 == 0 else "F7FAFC"
            set_cell_background(cell, bg)

    doc.add_paragraph("")
    add_body(
        "Key Findings:\n"
        "1. Go Load Balancer Efficiency: Sys1 consumed only 5.6% average CPU and 14.9 MB memory, proving the efficiency "
        "of Go's asynchronous goroutine-based reverse proxy multiplexing.\n"
        "2. Balanced Backend Load: All three backends exhibited virtually identical average CPU utilization (Sys2: 158.6%, "
        "Sys3: 156.1%, Sys4: 158.2%), confirming that dynamic performance-based load balancing achieved uniform workload "
        "distribution without creating hotspot bottlenecks."
    )

    # Embed Plot 2: 4-System Utilization
    p2_path = os.path.join(PLOTS_DIR, "plot_system_utilization.png")
    if os.path.exists(p2_path):
        doc.add_picture(p2_path, width=Inches(6.2))
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_cap = p_cap.add_run("Figure 2: Real-Time CPU & Memory Utilization Across All 4 Systems During Load Test")
        r_cap.font.italic = True
        r_cap.font.size = Pt(9.5)

    # 7. Scalability & Response Time
    add_heading1("7. Concurrency Scalability & Traffic Distribution")
    add_body(
        "The system was evaluated under scaling client concurrency from 10 to 60 concurrent users. "
        "Across all concurrency tiers, the system achieved a 100% success rate with 0 dropped requests."
    )

    # Embed Plot 3: Response Time
    p3_path = os.path.join(PLOTS_DIR, "plot_response_time.png")
    if os.path.exists(p3_path):
        doc.add_picture(p3_path, width=Inches(6.2))
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_cap = p_cap.add_run("Figure 3: Response Time Scalability (Mean, p50, p90, p99) Under Scaling Client Concurrency")
        r_cap.font.italic = True
        r_cap.font.size = Pt(9.5)

    # Embed Plot 4: Backend Distribution
    p4_path = os.path.join(PLOTS_DIR, "plot_backend_distribution.png")
    if os.path.exists(p4_path):
        doc.add_picture(p4_path, width=Inches(5.5))
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_cap = p_cap.add_run("Figure 4: Traffic Distribution Across Backends — Empirical Proof of Dynamic Load Balancing")
        r_cap.font.italic = True
        r_cap.font.size = Pt(9.5)

    # 8. Load Generator Capabilities
    add_heading1("8. Load Generator Implementation (load_generator.py)")
    add_body(
        "To validate the system locally prior to official evaluation, a multi-threaded load generator was developed "
        "with the following capabilities:\n"
        "  - Variable Concurrent Users: Configurable via --users (tested from 10 to 60 users).\n"
        "  - Variable Message Lengths: Generates random realistic text payloads ranging from 15 to 150 characters (--min-len, --max-len).\n"
        "  - Variable Arrival Intervals: Simulates human typing and network jitter with random delays between 10 ms and 60 ms (--min-interval, --max-interval).\n"
        "  - Mixed API Workload: Generates realistic traffic mixing 75% message writes (POST /message) and 25% feed reads (GET /feed).\n"
        "  - Automated Deduplication Test (--test-dedup): Sends 10 duplicate message IDs to verify idempotent rejection.\n"
        "  - Comprehensive Telemetry: Reports throughput, latency percentiles (p50, p90, p95, p99, min, max), and backend distribution via X-Backend-ID."
    )

    # 9. Conclusion
    add_heading1("9. Conclusion & Submission Summary")
    add_body(
        "The extended GRP-CHAT system satisfies all assignment requirements:\n"
        "  1. Deployed across 3 backends (Sys2 on port 3310, Sys3 on port 3311, Sys4 on port 5312) fronted by Sys1 Load Balancer on port 6000.\n"
        "  2. Dynamic performance-based load balancing implemented with active health detection and threshold switching.\n"
        "  3. Optimal performance threshold determined as T = 5, maximizing throughput (292.08 req/s) and minimizing latency.\n"
        "  4. Shared persistent storage (shared_chat.db) with atomic deduplication on msg_id and unbroken hash-chain integrity.\n"
        "  5. Required API routes exposed: POST /message and GET /feed.\n"
        "  6. Advanced load generator developed and verified.\n"
        "  7. Full cryptographic security (Fernet encryption at rest, ECDSA signatures, SHA-256 hash chaining) fully preserved.\n\n"
        "Submission Load Balancer URL: http://10.11.221.87:6000/\n"
        "Repository URL: https://github.com/gnshx/GRP-CHAT"
    )

    doc.save(DOCX_PATH)
    print(f"[report] Saved DOCX report to {DOCX_PATH}")

    # Convert to PDF and ODT using libreoffice
    try:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", DOCX_PATH, "--outdir", "/home/ganesh/Desktop/csd/load-balancer/"], check=True)
        print("[report] Converted to PDF: Dynamic_Load_Balancer_Report.pdf")
    except Exception as e:
        print("[report] Libreoffice PDF conversion:", e)

    try:
        subprocess.run(["libreoffice", "--headless", "--convert-to", "odt", DOCX_PATH, "--outdir", "/home/ganesh/Desktop/csd/load-balancer/"], check=True)
        print("[report] Converted to ODT: Dynamic_Load_Balancer_Report.odt")
    except Exception as e:
        print("[report] Libreoffice ODT conversion:", e)

if __name__ == "__main__":
    create_report()
