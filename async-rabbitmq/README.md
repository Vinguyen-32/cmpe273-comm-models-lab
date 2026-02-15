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

### Test Descriptions

| Test | What It Proves |
|------|---------------|
| `test_order_placed_and_reserved` | Happy path: order → reserve → status updated |
| `test_notification_sent` | NotificationService receives InventoryReserved event |
| `test_kill_inventory_publish_orders_restart` | **Backlog drain**: messages queue up while consumer is down, then drain on restart |
| `test_duplicate_order_placed_no_double_reserve` | **Idempotency**: same OrderPlaced delivered twice → only 1 reservation |
| `test_malformed_message_goes_to_dlq` | **DLQ**: malformed message NACKed → routed to dead-letter queue |

---

## Failure Injection Details

### 1. Backlog Drain (Consumer Down for 60s)

```bash
# Stop inventory service
docker compose stop inventory_service

# Publish 10 orders (they queue up in RabbitMQ)
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:5001/order \
    -H "Content-Type: application/json" \
    -d "{\"item\":\"Coffee\",\"qty\":1,\"student_id\":\"S$i\"}"
done

# Check backlog in RabbitMQ UI → order_placed queue will show 10 ready messages

# Restart inventory service
docker compose start inventory_service

# Watch logs – all 10 messages drain within seconds
docker compose logs -f inventory_service
```

**Why it works:** RabbitMQ durably stores messages. When the consumer reconnects, messages are delivered in FIFO order. The producer (OrderService) is never blocked — it returns `201` immediately because the `publish` call is fire-and-forget to the broker.

### 2. Idempotency (Duplicate Message)

The InventoryService maintains an in-memory set `processed_order_ids`. When it receives an `OrderPlaced` event:

1. It checks whether `order_id` has already been processed.
2. If **yes** → it logs a warning and ACKs the message (no-op).
3. If **no** → it performs the reservation and adds the ID to the set.

**Strategy:** Application-level deduplication using a processed-ID set. In production this would be backed by a database or Redis with a TTL.

### 3. DLQ / Poison Message

The `order_placed` queue is configured with:
```json
{
  "x-dead-letter-exchange": "",
  "x-dead-letter-routing-key": "order_placed_dlq"
}
```

When InventoryService receives a message it cannot parse (invalid JSON, missing required fields), it calls `basic_nack(requeue=False)`. RabbitMQ then routes the message to `order_placed_dlq` instead of discarding it, allowing later inspection.

---

## Tear Down

```bash
docker compose down -v
```
