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

### Tests outputs
<img width="712" height="228" alt="image" src="https://github.com/user-attachments/assets/2aab7008-21b3-4d93-8953-dc188c90903a" />
<img width="733" height="423" alt="image" src="https://github.com/user-attachments/assets/32bed67f-f3e8-4fcd-ae3c-34f6c055641e" />

### Manual Failure Injection (Backlog Drain)
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
```
<img width="944" height="320" alt="image" src="https://github.com/user-attachments/assets/d0790a44-3da4-47e1-9d3c-ce082819db52" />
<img width="873" height="315" alt="image" src="https://github.com/user-attachments/assets/d8bb5f8a-056e-4aa6-9dc0-805c13e82a06" />

# Check RabbitMQ UI → order_placed queue shows 10 ready messages
# Or via CLI:
# The orders are queued, OrderService returned 201 for all of them

# Restart inventory
docker compose start inventory_service

# Watch all 10 drain instantly
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
