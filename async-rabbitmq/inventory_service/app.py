"""
InventoryService – Consumes OrderPlaced events, attempts to reserve
inventory, and publishes InventoryReserved or InventoryFailed.

Idempotency:
  Tracks processed order_ids in a set. If the same OrderPlaced message
  is delivered again (duplicate / re-delivery), the service skips the
  reservation logic and simply ACKs the message.

DLQ / Poison-message handling:
  If a message cannot be parsed (malformed JSON, missing fields) the
  service NACKs with requeue=False, causing RabbitMQ to route it to the
  dead-letter queue (order_placed_dlq) configured on the order_placed queue.
"""

import os, json, time, logging
import pika

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [InventoryService] %(message)s")
log = logging.getLogger(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", 5672))
EXCHANGE = "orders_exchange"

# ── In-memory inventory & idempotency state ──────────────────
inventory: dict[str, int] = {
    "Pizza":    50,
    "Burger":   50,
    "Sushi":    50,
    "Salad":    50,
    "Taco":     50,
    "Sandwich": 50,
    "Pasta":    50,
    "Coffee":   100,
}

processed_order_ids: set[str] = set()   # idempotency guard


# ── RabbitMQ helpers ─────────────────────────────────────────
def connect():
    for attempt in range(15):
        try:
            return pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBIT_HOST, port=RABBIT_PORT,
                                          heartbeat=600,
                                          blocked_connection_timeout=300)
            )
        except pika.exceptions.AMQPConnectionError:
            log.warning("RabbitMQ not ready, retry %d …", attempt + 1)
            time.sleep(3)
    raise RuntimeError("Cannot connect to RabbitMQ")


def publish(ch, routing_key: str, body: dict):
    ch.basic_publish(
        exchange=EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(body),
        properties=pika.BasicProperties(delivery_mode=2,
                                        content_type="application/json"),
    )
    log.info("Published %s → %s", routing_key, body.get("order_id"))


# ── Message handler ──────────────────────────────────────────
def on_order_placed(ch, method, properties, body):
    # ── 1. Parse (poison-message guard) ──────────────────────
    try:
        event = json.loads(body)
        order_id = event["order_id"]
        item = event["item"]
        qty = event["qty"]
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Malformed message → DLQ: %s | error: %s",
                  body[:200], exc)
        # NACK without requeue → routed to order_placed_dlq
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    # ── 2. Idempotency check ─────────────────────────────────
    if order_id in processed_order_ids:
        log.warning("Duplicate OrderPlaced for %s – skipping", order_id)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    # ── 3. Reserve inventory ─────────────────────────────────
    current_stock = inventory.get(item, 0)
    if current_stock >= qty:
        inventory[item] = current_stock - qty
        processed_order_ids.add(order_id)
        log.info("Reserved %d × %s for %s (remaining: %d)",
                 qty, item, order_id, inventory[item])
        publish(ch, "inventory.reserved", {
            "order_id": order_id,
            "item": item,
            "qty": qty,
            "remaining_stock": inventory[item],
        })
    else:
        processed_order_ids.add(order_id)
        reason = f"insufficient stock for {item} (have {current_stock}, need {qty})"
        log.warning("Reservation FAILED for %s: %s", order_id, reason)
        publish(ch, "inventory.failed", {
            "order_id": order_id,
            "item": item,
            "qty": qty,
            "reason": reason,
        })

    ch.basic_ack(delivery_tag=method.delivery_tag)


# ── REST health endpoint (optional, runs in a thread) ───────
def start_health_server():
    """Tiny health-check endpoint so docker-compose can probe."""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"inventory_service"}')
        def log_message(self, *_): ...  # silence logs

    import threading
    t = threading.Thread(target=HTTPServer(("", 5002), H).serve_forever,
                         daemon=True)
    t.start()


# ── Main ─────────────────────────────────────────────────────
def main():
    start_health_server()
    conn = connect()
    ch = conn.channel()

    ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)

    # Declare queues (with DLQ wiring)
    ch.queue_declare(queue="order_placed", durable=True, arguments={
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "order_placed_dlq",
    })
    ch.queue_declare(queue="order_placed_dlq", durable=True)

    ch.queue_bind(queue="order_placed", exchange=EXCHANGE,
                  routing_key="order.placed")

    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue="order_placed",
                     on_message_callback=on_order_placed)

    log.info("Consuming order_placed queue …")
    ch.start_consuming()


if __name__ == "__main__":
    main()
