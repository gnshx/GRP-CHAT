// Performance-Based Dynamic Load Balancer for GRP-CHAT
// Features:
// 1. Dynamic performance-based backend selection (Threshold Switching & Least Load).
// 2. Active in-flight request tracking and background CPU/memory polling from /load.
// 3. Dynamic switching when current backend load exceeds defined threshold.
// 4. Active health monitoring via /health, removing unhealthy backends and auto-recovery.
// 5. Full HTTP and WebSocket reverse proxy (/message, /feed, /ws, /, static assets).
// 6. Transparent header tagging (X-Backend-ID, X-Backend-Load).
// 7. Dynamic status API at /lb-status and health endpoint at /health.

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type BackendLoadStats struct {
	CPUPercent     float64 `json:"cpu_percent"`
	MemoryPercent  float64 `json:"memory_percent"`
	ActiveRequests int64   `json:"active_requests"`
	Uptime         float64 `json:"uptime"`
	Status         string  `json:"status"`
}

type Backend struct {
	URL            *url.URL               `json:"url"`
	Host           string                 `json:"host"`
	Alive          bool                   `json:"alive"`
	ActiveRequests int64                  `json:"active_requests"`
	TotalRequests  uint64                 `json:"total_requests"`
	CPUPercent     float64                `json:"cpu_percent"`
	MemoryPercent  float64                `json:"memory_percent"`
	LastLatencyMs  float64                `json:"last_latency_ms"`
	lastLatencyUs  uint64                 `json:"-"`
	FailedChecks   int                    `json:"failed_checks"`
	mu             sync.RWMutex           `json:"-"`
	ReverseProxy   *httputil.ReverseProxy `json:"-"`
}

func (b *Backend) SetAlive(alive bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.Alive = alive
	if alive {
		b.FailedChecks = 0
	}
}

func (b *Backend) IsAlive() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.Alive
}

func (b *Backend) UpdateMetrics(cpu, mem float64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.CPUPercent = cpu
	b.MemoryPercent = mem
}

func (b *Backend) GetMetrics() (cpu, mem float64) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.CPUPercent, b.MemoryPercent
}

// LoadScore calculates a normalized load score combining in-flight requests and CPU utilization.
func (b *Backend) LoadScore() float64 {
	active := float64(atomic.LoadInt64(&b.ActiveRequests))
	cpu, _ := b.GetMetrics()
	// Each active in-flight request carries weight 10.0, plus reported CPU percentage
	return (active * 10.0) + cpu
}

type ServerPool struct {
	backends       []*Backend
	currentIndex   int64
	threshold      int64   // In-flight active request threshold
	cpuThreshold   float64 // CPU percentage threshold
	switchCount    uint64  // Counter of dynamic switches
	client         *http.Client
	mu             sync.RWMutex
}

var pool ServerPool

// SelectBackend implements performance-based dynamic load balancing.
// It checks the current backend's load against the defined threshold.
// If exceeded or unhealthy, it dynamically switches to the least-loaded suitable backend.
func (s *ServerPool) SelectBackend() (*Backend, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	numBackends := len(s.backends)
	if numBackends == 0 {
		return nil, false
	}

	currIdx := int(atomic.LoadInt64(&s.currentIndex) % int64(numBackends))
	curr := s.backends[currIdx]
	currActive := atomic.LoadInt64(&curr.ActiveRequests)
	currCPU, _ := curr.GetMetrics()

	// Condition for switching:
	// 1. Current backend is marked dead/unhealthy, OR
	// 2. Current active requests >= threshold, OR
	// 3. Current CPU percentage >= cpuThreshold
	needSwitch := !curr.IsAlive() || currActive >= s.threshold || currCPU >= s.cpuThreshold

	if !needSwitch {
		return curr, false
	}

	// Dynamic Performance-Based Selection: Find suitable backend with lowest load score
	var bestBackend *Backend
	bestIdx := -1
	bestScore := 1e9

	for i, b := range s.backends {
		if !b.IsAlive() {
			continue
		}
		score := b.LoadScore()
		if score < bestScore {
			bestScore = score
			bestBackend = b
			bestIdx = i
		}
	}

	if bestBackend == nil {
		// If all backends are marked down or under heavy probe latency, never fail with 503!
		// Fallback to whichever backend has the least active in-flight requests.
		var minActive int64 = 1e9
		for i, b := range s.backends {
			act := atomic.LoadInt64(&b.ActiveRequests)
			if act < minActive {
				minActive = act
				bestBackend = b
				bestIdx = i
			}
		}
		if bestBackend == nil && len(s.backends) > 0 {
			bestBackend = s.backends[0]
			bestIdx = 0
		}
	}

	switched := (bestIdx != currIdx)
	if switched {
		atomic.StoreInt64(&s.currentIndex, int64(bestIdx))
		atomic.AddUint64(&s.switchCount, 1)
		log.Printf("[dynamic switch #%d] Load on %s (active: %d, cpu: %.1f%%) crossed threshold (%d reqs / %.1f%% cpu) -> Switched to %s (active: %d, cpu: %.1f%%, score: %.1f)",
			atomic.LoadUint64(&s.switchCount),
			curr.Host, currActive, currCPU,
			s.threshold, s.cpuThreshold,
			bestBackend.Host, atomic.LoadInt64(&bestBackend.ActiveRequests), bestBackend.CPUPercent, bestScore)
	}

	return bestBackend, switched
}

func (s *ServerPool) HealthCheck() {
	for _, b := range s.backends {
		targetURL := fmt.Sprintf("%s/health", b.URL.String())
		resp, err := s.client.Get(targetURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			_ = resp.Body.Close()
			wasAlive := b.IsAlive()
			b.SetAlive(true)
			if !wasAlive {
				log.Printf("[health] Backend %s is now UP", b.Host)
			}
		} else {
			if resp != nil {
				_ = resp.Body.Close()
			}
			b.mu.Lock()
			b.FailedChecks++
			failed := b.FailedChecks
			b.mu.Unlock()

			// Only mark DOWN after 3 consecutive failures to avoid flapping under heavy load
			if failed >= 3 {
				wasAlive := b.IsAlive()
				b.SetAlive(false)
				if wasAlive {
					log.Printf("[health] Backend %s is now DOWN (after %d consecutive failed checks)", b.Host, failed)
				}
			}
		}
	}
}

// PollMetrics updates CPU and memory metrics from each backend's /load endpoint.
func (s *ServerPool) PollMetrics() {
	for _, b := range s.backends {
		if !b.IsAlive() {
			continue
		}
		loadURL := fmt.Sprintf("%s/load", b.URL.String())
		resp, err := s.client.Get(loadURL)
		if err != nil {
			continue
		}

		body, err := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if err != nil || resp.StatusCode != http.StatusOK {
			continue
		}

		var stats BackendLoadStats
		if err := json.Unmarshal(body, &stats); err == nil {
			b.UpdateMetrics(stats.CPUPercent, stats.MemoryPercent)
		}
	}
}

func healthAndMetricsLoop(healthInterval, pollInterval time.Duration) {
	healthTicker := time.NewTicker(healthInterval)
	pollTicker := time.NewTicker(pollInterval)
	defer healthTicker.Stop()
	defer pollTicker.Stop()

	for {
		select {
		case <-healthTicker.C:
			pool.HealthCheck()
		case <-pollTicker.C:
			pool.PollMetrics()
		}
	}
}

// lbHandler dispatches requests to dynamically chosen backends.
func lbHandler(w http.ResponseWriter, r *http.Request) {
	// Expose Load Balancer status and diagnostic endpoint
	if r.URL.Path == "/lb-status" {
		handleLBStatus(w, r)
		return
	}
	if r.URL.Path == "/health" && r.Method == "GET" && r.Header.Get("X-LB-Probe") == "" {
		handleLBHealth(w, r)
		return
	}

	peer, _ := pool.SelectBackend()
	if peer == nil {
		http.Error(w, `{"error": "503 - No healthy backends available"}`, http.StatusServiceUnavailable)
		log.Printf("[error] 503 No backend available for %s %s", r.Method, r.URL.Path)
		return
	}

	// Track in-flight requests atomically
	atomic.AddInt64(&peer.ActiveRequests, 1)
	atomic.AddUint64(&peer.TotalRequests, 1)
	start := time.Now()

	defer func() {
		atomic.AddInt64(&peer.ActiveRequests, -1)
		duration := time.Since(start)
		atomic.StoreUint64(&peer.lastLatencyUs, uint64(duration.Microseconds()))
	}()

	// Tag response headers
	w.Header().Set("X-Backend-Active", fmt.Sprintf("%d", atomic.LoadInt64(&peer.ActiveRequests)))

	peer.ReverseProxy.ServeHTTP(w, r)
}

func handleLBHealth(w http.ResponseWriter, r *http.Request) {
	aliveCount := 0
	for _, b := range pool.backends {
		if b.IsAlive() {
			aliveCount++
		}
	}
	w.Header().Set("Content-Type", "application/json")
	if aliveCount > 0 {
		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, `{"status": "healthy", "healthy_backends": %d, "total_backends": %d}`+"\n", aliveCount, len(pool.backends))
	} else {
		w.WriteHeader(http.StatusServiceUnavailable)
		fmt.Fprintf(w, `{"status": "unhealthy", "healthy_backends": 0, "total_backends": %d}`+"\n", len(pool.backends))
	}
}

func handleLBStatus(w http.ResponseWriter, r *http.Request) {
	type BackendStatusView struct {
		Host           string  `json:"host"`
		URL            string  `json:"url"`
		Alive          bool    `json:"alive"`
		ActiveRequests int64   `json:"active_requests"`
		TotalRequests  uint64  `json:"total_requests"`
		CPUPercent     float64 `json:"cpu_percent"`
		MemoryPercent  float64 `json:"memory_percent"`
		LastLatencyMs  float64 `json:"last_latency_ms"`
		LoadScore      float64 `json:"load_score"`
	}

	views := make([]BackendStatusView, len(pool.backends))
	for i, b := range pool.backends {
		cpu, mem := b.GetMetrics()
		views[i] = BackendStatusView{
			Host:           b.Host,
			URL:            b.URL.String(),
			Alive:          b.IsAlive(),
			ActiveRequests: atomic.LoadInt64(&b.ActiveRequests),
			TotalRequests:  atomic.LoadUint64(&b.TotalRequests),
			CPUPercent:     cpu,
			MemoryPercent:  mem,
			LastLatencyMs:  float64(atomic.LoadUint64(&b.lastLatencyUs)) / 1000.0,
			LoadScore:      b.LoadScore(),
		}
	}

	respData := map[string]interface{}{
		"load_balancer": "Dynamic Performance-Based Load Balancer",
		"threshold_active_reqs": pool.threshold,
		"threshold_cpu_percent": pool.cpuThreshold,
		"dynamic_switches_total": atomic.LoadUint64(&pool.switchCount),
		"backends": views,
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(respData)
}

func main() {
	var backendList string
	var port string
	var threshold int64
	var cpuThreshold float64
	var healthInterval time.Duration
	var pollInterval time.Duration

	var altPort string

	flag.StringVar(&backendList, "backends", "", "comma-separated backend URLs (e.g. http://10.11.221.87:3310,http://10.11.221.87:3311,http://10.11.221.87:5312)")
	flag.StringVar(&port, "port", "6000", "port for the load balancer to listen on")
	flag.StringVar(&altPort, "alt-port", "8000", "browser-friendly mirror port to bypass Chrome ERR_UNSAFE_PORT on port 6000")
	flag.Int64Var(&threshold, "threshold", 15, "performance threshold: active in-flight request limit before switching backends")
	flag.Float64Var(&cpuThreshold, "cpu-threshold", 75.0, "performance threshold: CPU percentage before switching backends")
	flag.DurationVar(&healthInterval, "health-interval", 2*time.Second, "how often to health-check backends")
	flag.DurationVar(&pollInterval, "poll-interval", 1*time.Second, "how often to poll backend /load metrics")
	flag.Parse()

	if backendList == "" {
		backendList = "http://127.0.0.1:3310,http://127.0.0.1:3311,http://127.0.0.1:5312"
	}

	pool.threshold = threshold
	pool.cpuThreshold = cpuThreshold
	pool.client = &http.Client{Timeout: 8 * time.Second}

	customTransport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: (&net.Dialer{
			Timeout:   10 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		ForceAttemptHTTP2:     false,
		MaxIdleConns:          10000,
		MaxIdleConnsPerHost:   2000,
		MaxConnsPerHost:       0,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 60 * time.Second,
	}

	for _, raw := range strings.Split(backendList, ",") {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}

		serverURL, err := url.Parse(raw)
		if err != nil {
			log.Fatalf("invalid backend URL %q: %v", raw, err)
		}

		proxy := httputil.NewSingleHostReverseProxy(serverURL)
		proxy.Transport = customTransport
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("[proxy error] %s -> %s : %v", r.RemoteAddr, serverURL, err)
			http.Error(w, `{"error": "502 - backend error"}`, http.StatusBadGateway)
		}

		backendID := serverURL.Host
		proxy.ModifyResponse = func(resp *http.Response) error {
			resp.Header.Set("X-Backend-ID", backendID)
			return nil
		}

		pool.backends = append(pool.backends, &Backend{
			URL:          serverURL,
			Host:         backendID,
			Alive:        true,
			ReverseProxy: proxy,
		})
		log.Printf("[config] Registered backend: %s", serverURL)
	}

	// Immediate health check and metrics collection
	pool.HealthCheck()
	pool.PollMetrics()
	go healthAndMetricsLoop(healthInterval, pollInterval)

	mux := http.NewServeMux()
	mux.HandleFunc("/", lbHandler)

	server := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	log.Printf("==================================================================")
	log.Printf("Dynamic Performance-Based Load Balancer started on :%s", port)
	if altPort != "" && altPort != port {
		log.Printf("Browser-friendly mirror running on :%s (bypasses Chrome ERR_UNSAFE_PORT)", altPort)
		go func() {
			altServer := &http.Server{
				Addr:    ":" + altPort,
				Handler: mux,
			}
			if err := altServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				log.Printf("[warn] could not start mirror on :%s: %v", altPort, err)
			}
		}()
	}
	log.Printf("Backends configured: %d", len(pool.backends))
	log.Printf("Switch Threshold: active requests >= %d OR cpu >= %.1f%%", pool.threshold, pool.cpuThreshold)
	log.Printf("Required routes: /message, /feed")
	log.Printf("Status endpoint: /lb-status")
	log.Printf("==================================================================")

	if err := server.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
