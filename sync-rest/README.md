# Sync REST (Part A)

## Overview
Synchronous REST implementation of campus food ordering. OrderService calls Inventory and Notification services sequentially, blocking on each call.

## Services and endpoints
- OrderService: POST /order (port 8080)
- InventoryService: POST /reserve, POST /inject (port 8081)
- NotificationService: POST /send (port 8082)

## Prerequisites
- Docker
- Maven 3.9+
- Java 17+

## Build and run
```bash
docker compose -f sync-rest/docker-compose.yml up --build
```

## Tests (JUnit)
```bash
cd sync-rest/tests
mvn -q test
```

## Failure injection
InventoryService supports control endpoint:
- POST /inject

Example payload:
```json
{"delayMs":2000,"forceFail":false}
```

Delay adds latency to /order. Setting forceFail=true makes /reserve return 500.

## Example order request
```json
{"studentId":"s-100","items":[{"itemId":"burger","qty":1}]}
```

---

# Part A Results

## Latency Analysis

| Scenario | Avg Latency (ms) | P95 Latency (ms) | Success Rate |
|----------|------------------|-----------------|--------------|
| Baseline (no delay) | 11.95 | 19 | 100% |
| Inventory delay 2s | 2085.8 | 2301 | 100% |
| Inventory failure | HTTP 502 | - | 0% |

## Explanation

### Why sync calls add latency

In synchronous REST, OrderService **blocks** on the HTTP call to Inventory. The client waits for the complete chain:
1. OrderService → Inventory (2000ms delay)
2. Wait for Inventory response
3. OrderService → Notification
4. Return to client

**Result**: The 2000ms delay in Inventory propagates directly to the client, adding ~2000ms to the Order response time.

### Why failures propagate

When Inventory fails:
- OrderService receives a 500/timeout error
- OrderService catches the exception and returns HTTP 502 (Bad Gateway) to client
- Notification is **not called** (the chain stops)

This is **blocking failure propagation**—synchronous calls fail fast and synchronously.

### Key observation

Synchronous REST is simple but tightly couples services. Any delay or failure in a dependency directly impacts upstream services and clients. This is why async/streaming models are often preferred in microservices.
