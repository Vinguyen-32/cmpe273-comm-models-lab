# CMPE 273 - Communication Models Lab

Campus food ordering workflow implemented using three communication models:
- **Part A**: Synchronous REST
- **Part B**: Async Messaging with RabbitMQ
- **Part C**: Streaming with Kafka

---

# Part A: Synchronous REST

## Architecture

```
Client ──▶ OrderService ──▶ InventoryService
                │                  │
                │◀─── reserve ─────┘
                │
                └──▶ NotificationService
                           │
                ◀─── send ─┘
```

All calls are **synchronous and blocking**. OrderService waits for each downstream service before proceeding.

## Services

| Service | Port | Endpoints |
|---------|------|-----------|
| OrderService | 8080 | `POST /order` |
| InventoryService | 8081 | `POST /reserve`, `POST /inject` |
| NotificationService | 8082 | `POST /send` |

## Build and Run

```bash
docker compose -f sync-rest/docker-compose.yml up --build
```

## Run Tests

```bash
cd sync-rest/tests
mvn clean test
```

## Failure Injection

Use InventoryService `/inject` endpoint to simulate delay or failure:

```bash
# Add 2s delay
curl -X POST http://localhost:8081/inject -H "Content-Type: application/json" \
  -d '{"delayMs":2000,"forceFail":false}'

# Force failure
curl -X POST http://localhost:8081/inject -H "Content-Type: application/json" \
  -d '{"delayMs":0,"forceFail":true}'

# Reset to normal
curl -X POST http://localhost:8081/inject -H "Content-Type: application/json" \
  -d '{"delayMs":0,"forceFail":false}'
```

---

## Test Results

| Scenario | Avg Latency (ms) | P95 (ms) | Status |
|----------|------------------|----------|--------|
| Baseline (N=20) | 11.95 | 19 | 200 OK |
| Inventory 2s delay | 2085.8 | 2301 | 200 OK |
| Inventory failure | - | - | 502 Bad Gateway |

## Reasoning

**Delay propagation**: Synchronous calls block. OrderService waits for Inventory before calling Notification. A 2s delay in Inventory adds ~2s to total response time.

**Failure handling**: When Inventory fails, OrderService returns HTTP 502. Notification is never called—the chain stops at the failed step.

**Key insight**: Sync REST creates tight coupling. Any downstream delay or failure directly impacts client response time.

# Part B – Async Messaging with RabbitMQ

Campus food ordering workflow using **asynchronous event-driven messaging** via RabbitMQ.

## Architecture

```
┌─────────────┐    POST /order    ┌──────────────────┐
│   Client    │ ─────────────────▶│  OrderService    │
│  (tests)    │ ◀─────────────────│  (Flask :5001)   │
└─────────────┘    201 + order    └────────┬─────────┘
                                           │ publish
                                           ▼
                                  ┌──────────────────┐
                                  │    RabbitMQ       │
                                  │  orders_exchange  │
                                  │  (topic)          │
                                  └──┬──────────┬─────┘
                   order.placed      │          │  inventory.reserved
                                     ▼          ▼
                            ┌────────────┐  ┌────────────────────┐
                            │ Inventory  │  │ NotificationService│
                            │ Service    │  │     (:5003)        │
                            │  (:5002)   │  └────────────────────┘
                            └──────┬─────┘        ▲
                                   │ publish      │ consume
                                   │ inventory.   │ inventory.reserved
                                   │ reserved     │
                                   └──────────────┘
```

### Event Flow

1. **OrderService** receives `POST /order`, saves to local store, publishes `OrderPlaced` → `order.placed`
2. **InventoryService** consumes `order.placed`, reserves stock, publishes `InventoryReserved` → `inventory.reserved` (or `InventoryFailed` → `inventory.failed`)
3. **NotificationService** consumes `inventory.reserved`, logs confirmation notification
4. **OrderCallback** (sidecar) consumes `inventory.reserved` / `inventory.failed`, updates order status in OrderService

### Queues & Exchanges

| Exchange | Type | Routing Key | Queue | Purpose |
|----------|------|-------------|-------|---------|
| `orders_exchange` | topic | `order.placed` | `order_placed` | New orders |
| `orders_exchange` | topic | `inventory.reserved` | `inventory_reserved` | Successful reservations |
| `orders_exchange` | topic | `inventory.failed` | `inventory_failed` | Failed reservations |
| (default) | direct | `order_placed_dlq` | `order_placed_dlq` | Dead-letter queue for poison messages |

---

## Build & Run

```bash
cd async-rabbitmq

# Build and start all services
docker compose up --build -d

# Verify everything is running
docker compose ps

# Check RabbitMQ management UI
open http://localhost:15672   # guest / guest
```
### Outputs

<img width="700" height="158" alt="image" src="https://github.com/user-attachments/assets/3b8f02ef-4cff-450b-be9a-4b88927c0556" />

<img width="715" height="172" alt="image" src="https://github.com/user-attachments/assets/d7664005-8cd0-474f-b4f6-d4101c202853" />

<img width="796" height="132" alt="image" src="https://github.com/user-attachments/assets/c01ddb0e-e123-4457-9022-eace66ecb897" />

## Restart inventory
docker compose start inventory_service

## Watch all 10 drain instantly
docker compose logs -f inventory_service

### Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| RabbitMQ AMQP | 5672 | Message broker |
| RabbitMQ UI | 15672 | Management dashboard |
| OrderService | 5001 | REST API |
| InventoryService | 5002 | Health check |
| NotificationService | 5003 | Health + `/notifications` |

---

## Test

### Install test dependencies

```bash
pip install -r tests/requirements.txt
```

### Run all tests

```bash
python -m pytest tests/test_async.py -v -s
```
<img width="1075" height="624" alt="image" src="https://github.com/user-attachments/assets/b1412391-2d51-42df-87d5-90eb84d476c6" />

### Tests outputs
<img width="712" height="228" alt="image" src="https://github.com/user-attachments/assets/2aab7008-21b3-4d93-8953-dc188c90903a" />
<img width="733" height="423" alt="image" src="https://github.com/user-attachments/assets/32bed67f-f3e8-4fcd-ae3c-34f6c055641e" />

# Part C — Streaming Test Suite

## Setup

```bash
# 1. Start Kafka
docker-compose up -d

# 2. Install dependency (if not already)
pip install kafka-python

# 3. Run all tests
python test_streaming.py
```

## What the tests do

| Test | What it checks | Pass condition |
|------|---------------|----------------|
| **Test 1** | Produces 10 000 `OrderPlaced` events | All 10k sent, throughput printed |
| **Test 2** | Inventory consumer with 5ms throttle | Lag table shows growing backlog |
| **Test 3** | Offset reset → replay → compare metrics | Event counts match; failure rate delta explained |

## Output

- **Console** — live progress + final comparison table
- **metrics_report.txt** — the file to submit

## Why failure rate differs on replay

The inventory consumer uses `random.random()` per message to decide availability.
That result is not stored in the order event itself — only the final
`available/out_of_stock` flag lands in `inventory-events`.
On replay, orders are re-consumed and the RNG runs again → different counts.
**Order counts and revenue metrics are fully deterministic and match exactly.**

## Adjusting throttle / failure rate

```bash
# Heavier throttle to show more lag
python test_streaming.py  # edit throttle_ms=50 inside the file

# Change event count
# edit COUNT = 10_000 at the top of test_produce_10k()
```

