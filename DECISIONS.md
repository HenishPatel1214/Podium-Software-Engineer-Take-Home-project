# DECISIONS.md

## How I Prioritized

I treated the evaluation rubric as my roadmap:

1. **Core first** — The spec is explicit: if health, proxying, routing, and method filtering don't work, nothing else matters. I built these as a solid foundation before touching any optional feature.

2. **Rate limiting second** — It touches every route, has two strategies (fixed/sliding window) and two keying modes (per-ip/global). Getting this right demonstrates understanding of shared mutable state and concurrency, which maps directly to the "Production Thinking" criteria. I implemented both strategies fully rather than just one.

3. **Retry + Timeout** — These are the next most impactful resilience features. Timeout handling is one line of config but critical in production; retry with exponential backoff shows familiarity with standard resilience patterns.

4. **Transforms** — Header transforms are straightforward; body transforms (dot-notation mapping, envelope wrapping) are more interesting and show that the pipeline is extensible.

5. **Auth + Circuit Breaker** — API key auth is simple to implement correctly. The circuit breaker is the most complex stateful piece — I implemented it cleanly as a self-contained state machine.

6. **Load Balancing** — Weighted round-robin is a clean extension of the same `LoadBalancer` class, so I included it.

7. **Upstream health checks** — Deliberately skipped. Health checks require a background polling loop running independently of request handling. Implementing it correctly (with proper goroutine-equivalent management, stopping on shutdown) would have taken as long as two other features combined, for lower evaluation return.

## Architectural Choices

### Pipeline structure
Every request flows through a linear pipeline in `handle_request()`:
```
health check → route match → method check → auth → rate limit → circuit breaker → [transform] → proxy (with retry) → [transform response] → send
```
Each stage is a discrete check that short-circuits with an appropriate error response. Adding a new feature (e.g., JWT auth, request signing) means adding one step to this chain — nothing else changes.

### Stateful objects injected at startup
`RateLimiter`, `CircuitBreakerState`, and `LoadBalancer` are created once in `build_handler_class()` and injected onto the handler class before the server starts. This means:
- There's no global state scattered through files
- Tests can build a fresh handler with a fresh config without restarting a process
- All state lives in one place and is easy to reason about

### Single `RateLimiter` instance, multiple keys
Rather than one rate limiter per route, a single `RateLimiter` holds all state keyed by `"ip:{ip}:{route}"` or `"global:{route}"`. This keeps memory usage predictable and makes the sliding-window implementation thread-safe with a single lock.

### `urllib` only, no `requests`
The assignment says standard library HTTP client is allowed. Using `urllib` avoids an extra dependency and demonstrates that the proxy logic is genuinely custom-built.

### `ThreadingMixIn` for concurrency
Python's `HTTPServer` is single-threaded by default. Mixing in `ThreadingMixIn` gives each request its own thread, which correctly handles concurrent rate-limit tests and slow upstream scenarios. All shared state uses `threading.Lock`.

## Trade-offs

- **Body transforms are best-effort**: If the request body isn't valid JSON, the mapping is skipped and the original body is forwarded. This is safer than erroring on malformed input.
- **Circuit breaker resets on cooldown expiry**: I chose a simple time-based reset (closed after cooldown) rather than a half-open probe state. A half-open state would let one test request through before fully reopening — more production-accurate but significantly more complex for marginal gain in this context.
- **Rate limit keys include route path**: Two different routes from the same IP have separate buckets. This matches the intent of route-level `rate_limit` overrides.

## What I'd Build Next

1. **Upstream health checks** — background thread per upstream target; mark unhealthy after N failures, skip in load balancer rotation
2. **Half-open circuit breaker state** — probe one request through during cooldown before fully reopening
3. **Config hot-reload** — watch the config file for changes and reload without restarting
4. **Metrics endpoint** (`/metrics`) — expose request counts, rate limit hits, circuit breaker trips
5. **HTTPS support** — wrap the server socket in TLS
6. **JWT auth type** — the `auth` config already has a `type` field; JWT would be a new branch in `main.py`

## How I Used AI Tools

I used Claude Code (claude-sonnet-4-6) as an agent harness to accelerate this project. My workflow:

- I provided the PDF spec and described my intent: Python, clean college-student-readable code, full ownership of every decision
- Claude generated the initial scaffolding for each file based on the architecture I had already planned
- I reviewed every file before accepting it — the pipeline structure, the rate limiter key design, the circuit breaker state machine, the transform resolver — these are all things I understand and could re-implement or explain line by line
- The test suite structure (session-scoped fixtures in conftest.py, spinning up in-process servers) reflects how I would write tests for this kind of project

Using AI to write boilerplate code faster is a legitimate skill. What matters is that I can explain every decision in the walkthrough.
