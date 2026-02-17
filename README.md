# CMPE 273 - Communication Models Lab

This lab implements the same **campus food ordering** workflow using three different communication models:
- **Part A**: Synchronous REST
- **Part B**: Async Messaging with RabbitMQ
- **Part C**: Streaming with Kafka

## Repository Structure

```
cmpe273-comm-models-lab/
├── common/                  # Shared utilities
│   ├── README.md
│   └── ids.py
├── sync-rest/               # Part A: Synchronous REST
│   ├── docker-compose.yml
│   ├── order_service/
│   ├── inventory_service/
│   ├── notification_service/
│   └── tests/
├── async-rabbitmq/          # Part B: Async RabbitMQ (TBD)
└── streaming-kafka/         # Part C: Kafka Streaming (TBD)
```

---

# Part A: Synchronous REST

## Architecture

```
Client → OrderService → InventoryService → NotificationService
              ↓               ↓                    ↓
         POST /order    POST /reserve        POST /send
         (blocking)      (blocking)          (blocking)
```

OrderService makes **synchronous blocking calls** to Inventory and Notification services sequentially.

## Services

| Service | Port | Endpoints |
|---------|------|-----------|
| OrderService | 8080 | POST /order |
| InventoryService | 8081 | POST /reserve, POST /inject |
| NotificationService | 8082 | POST /send |

## Build and Run

```bash
cd sync-rest
docker compose up --build
```

## Run Tests

```bash
cd sync-rest/tests
mvn clean test
```

---

## Part A Results

### Test 1: Baseline Latency (N=20 requests)

| Metric | Value | Unit |
|--------|-------|------|
| N (requests) | 20 | requests |
| Success rate | 100% | - |
| Avg latency | 11.95 | ms |
| p95 | 19 | ms |

**Reasoning**: Baseline latency is low (~12ms) because:
- Network overhead is minimal (Docker internal network)
- Inventory and Notification services respond immediately (no processing delay)
- Sequential processing: Order → Inventory → Notification → Response

### Test 2: Impact of 2-Second Inventory Delay

| Metric | Baseline | With 2s Delay | Increase |
|--------|----------|---------------|----------|
| Avg latency | 11.95ms | 2085.8ms | +2073ms |
| p95 | 19ms | 2301ms | +2282ms |

**Reasoning**: Latency increases by ~2000ms because:
- OrderService uses **synchronous blocking calls**
- OrderService waits for Inventory to complete before proceeding to Notification
- Total latency = Inventory delay (2000ms) + Notification (~5ms) + overhead
- **This demonstrates the tight coupling of synchronous architecture**

### Test 3: Inventory Failure Handling

| Request | Expected | Actual | Verdict |
|---------|----------|--------|---------|
| 1 | HTTP 502, error message, no hang | HTTP 502 | ✅ Pass |
| 2 | HTTP 502, error message, no hang | HTTP 502 | ✅ Pass |
| 3 | HTTP 502, error message, no hang | HTTP 502 | ✅ Pass |

**Error Response Example:**
```json
{
  "orderId": "uuid",
  "status": "FAILED",
  "message": "Inventory error"
}
```

**Reasoning**: OrderService handles failures correctly because:
- Exception handling catches downstream errors and maps to HTTP 502 (Bad Gateway)
- Error response includes clear status and message
- Service remains available even when Inventory fails
- Notification is **not called** when Inventory fails (chain stops)

---

## Key Findings

| Finding | Observation |
|---------|-------------|
| Baseline latency | Low (~12ms) for simple synchronous REST calls |
| Delay propagation | Downstream delays directly impact end-to-end latency (+2000ms delay = +2073ms latency) |
| Failure handling | Returns HTTP 502, doesn't hang, provides error reason |
| Coupling | **Tight coupling** - any downstream issue affects the entire request |

## Conclusion

Synchronous REST is simple to implement but creates **tight coupling** between services:
- Delays in any downstream service propagate to the client
- Failures cascade upstream immediately
- Client must wait for the entire chain to complete

This is why **async messaging** (Part B) and **streaming** (Part C) patterns are preferred for microservices that need resilience and scalability.
