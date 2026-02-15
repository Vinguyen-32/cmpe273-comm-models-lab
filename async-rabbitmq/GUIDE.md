# Part B – Async Messaging with RabbitMQ: Detailed Guide

## What Was Built

A **campus food ordering system** using asynchronous event-driven messaging with RabbitMQ. Instead of services calling each other directly (synchronous REST), each service communicates by **publishing and consuming messages through RabbitMQ queues**.

---

## Architecture Overview

```
Student places order
        │
        ▼
┌──────────────────┐   publishes "OrderPlaced"    ┌───────────────┐
│  OrderService    │ ──────────────────────────▶   │   RabbitMQ    │
│  (Flask :5001)   │                               │   Broker      │
│  POST /order     │                               │               │
└──────────────────┘                               │  order_placed │──▶ InventoryService
        ▲                                          │  queue        │    (reserves stock)
        │  updates status                          │               │
        │                                          │  inventory_   │◀── InventoryService
┌──────────────────┐   consumes reserved/failed    │  reserved     │    (publishes result)
│ CallbackListener │ ◀─────────────────────────    │  queue        │
│  (sidecar)       │                               │               │──▶ NotificationService
└──────────────────┘                               │  order_cb_    │    (sends confirmation)
                                                   │  reserved     │
                                                   │  queue        │──▶ CallbackListener
                                                   │               │    (updates order status)
                                                   │  order_placed │
                                                   │  _dlq         │    (poison messages land here)
                                                   └───────────────┘
```

---

## The 5 Containers

| Container | Role | Port |
|-----------|------|------|
| `rabbitmq` | Message broker (RabbitMQ 3.13 + management UI) | 5672 (AMQP), 15672 (UI) |
| `order_service` | REST API — accepts `POST /order`, saves locally, publishes `OrderPlaced` | 5001 |
| `inventory_service` | Consumer — listens for `OrderPlaced`, reserves stock, publishes `InventoryReserved` or `InventoryFailed` | 5002 |
| `notification_service` | Consumer — listens for `InventoryReserved`, logs a confirmation message | 5003 |
| `order_callback` | Consumer — listens for `InventoryReserved`/`InventoryFailed`, PATCHes order status back into OrderService | — |

---

## How RabbitMQ Helps

1. **Decoupling** — OrderService doesn't know or care if InventoryService is running. It publishes a message and returns `201` immediately. RabbitMQ holds the message until a consumer picks it up.

2. **Resilience** — If InventoryService goes down, messages **queue up durably** in RabbitMQ. When it comes back, all backlogged messages drain automatically. No orders are lost.

3. **Fan-out** — The `InventoryReserved` event is consumed by **two independent services** (NotificationService and CallbackListener) via separate queues bound to the same routing key. Each gets its own copy.

4. **Poison message handling** — Malformed messages are NACKed and routed to a **Dead Letter Queue (DLQ)** instead of being lost or crashing the consumer.

5. **Idempotency** — InventoryService tracks processed order IDs. If RabbitMQ re-delivers the same message (e.g., after a consumer crash before ACK), it won't double-reserve inventory.

---

## Step-by-Step Commands

### 1. Start Everything

```bash
cd ~/CMPE-273/cmpe273-comm-models-lab/async-rabbitmq
docker compose up --build -d
```

Wait ~15 seconds for RabbitMQ to become healthy, then verify:

```bash
docker compose ps
```

You should see all 5 containers with status `Up`.

### 2. Place an Order (Happy Path)

```bash
curl -s -X POST http://localhost:5001/order \
  -H "Content-Type: application/json" \
  -d '{"item":"Pizza","qty":2,"student_id":"S123"}' | python3 -m json.tool
```

This returns immediately with `status: "PLACED"`. Wait 3-5 seconds, then check:

```bash
curl -s http://localhost:5001/orders | python3 -m json.tool
```

The status should now be `"RESERVED"` — updated asynchronously by the callback listener after InventoryService processed it.

### 3. Check Notifications

```bash
curl -s http://localhost:5003/notifications | python3 -m json.tool
```

### 4. View RabbitMQ Management UI

Open http://localhost:15672 (login: `guest` / `guest`) to see queues, message rates, and bindings visually.

### 5. Watch Service Logs

```bash
docker compose logs -f inventory_service notification_service order_callback
```

### 6. Run the Full Test Suite

```bash
pip install requests pika pytest
cd ~/CMPE-273/cmpe273-comm-models-lab/async-rabbitmq
python -m pytest tests/test_async.py -v -s
```

This runs 5 tests:

| Test | What it proves |
|------|---------------|
| `test_order_placed_and_reserved` | Happy path works end-to-end |
| `test_notification_sent` | NotificationService receives the event |
| `test_kill_inventory_publish_orders_restart` | **Backlog drain**: messages survive a 60s outage |
| `test_duplicate_order_placed_no_double_reserve` | **Idempotency**: duplicate message → single reservation |
| `test_malformed_message_goes_to_dlq` | **DLQ**: bad messages go to dead-letter queue |

### 7. Manual Failure Injection (Backlog Drain)

```bash
# Stop inventory consumer
docker compose stop inventory_service

# Place 10 orders while it's down
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:5001/order \
    -H "Content-Type: application/json" \
    -d "{\"item\":\"Coffee\",\"qty\":1,\"student_id\":\"BACKLOG-$i\"}"
  echo ""
done

# Check RabbitMQ UI → order_placed queue shows 10 ready messages
# Or via CLI:
# The orders are queued, OrderService returned 201 for all of them

# Restart inventory
docker compose start inventory_service

# Watch all 10 drain instantly
docker compose logs -f inventory_service
```

### 8. Tear Down

```bash
docker compose down -v
```

---

## Key Files

```
async-rabbitmq/
├── broker/
│   └── rabbitmq.conf              # RabbitMQ config (allows remote guest login)
├── docker-compose.yml             # All 5 services orchestrated
├── order_service/
│   ├── app.py                     # Flask REST API + publishes OrderPlaced
│   └── callback_listener.py       # Consumes InventoryReserved → updates order
├── inventory_service/
│   └── app.py                     # Consumes OrderPlaced → reserves → publishes result
├── notification_service/
│   └── app.py                     # Consumes InventoryReserved → logs confirmation
└── tests/
    └── test_async.py              # 5 pytest tests covering all requirements
```

---

## Event Flow (Message-by-Message)

1. **Client** → `POST /order` → **OrderService** saves order locally (status=`PLACED`), returns `201`
2. **OrderService** publishes `OrderPlaced` event → routing key `order.placed` → **RabbitMQ** `orders_exchange`
3. **RabbitMQ** routes to `order_placed` queue
4. **InventoryService** consumes from `order_placed`, checks stock:
   - If stock available → decrements, publishes `InventoryReserved` → routing key `inventory.reserved`
   - If stock insufficient → publishes `InventoryFailed` → routing key `inventory.failed`
5. **RabbitMQ** routes `InventoryReserved` to two queues:
   - `inventory_reserved` → consumed by **NotificationService** (logs confirmation)
   - `order_callback_reserved` → consumed by **CallbackListener** (PATCHes order status to `RESERVED`)
6. **CallbackListener** calls `PATCH /orders/<id>/status` on **OrderService** → status becomes `RESERVED`

---

## Idempotency Strategy

InventoryService maintains an in-memory `processed_order_ids` set:
- On receiving `OrderPlaced`, it checks if `order_id` is already in the set.
- If **yes** → logs a warning, ACKs the message, does nothing (no duplicate reservation).
- If **no** → processes the reservation, adds `order_id` to the set, then ACKs.

In production, this set would be backed by a database or Redis with a TTL to survive restarts.

---

## DLQ (Dead Letter Queue) Strategy

The `order_placed` queue is configured with:
- `x-dead-letter-exchange: ""` (default exchange)
- `x-dead-letter-routing-key: "order_placed_dlq"`

When InventoryService receives a message it cannot parse (invalid JSON, missing required fields like `order_id`, `item`, `qty`), it calls `basic_nack(requeue=False)`. RabbitMQ then routes the rejected message to `order_placed_dlq` for later inspection, instead of discarding it.
