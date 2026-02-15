"""
NotificationService – Consumes InventoryReserved events and sends
a confirmation notification (logged to stdout in this lab).
"""

import os, json, time, logging
import pika

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [NotificationService] %(message)s")
log = logging.getLogger(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", 5672))
EXCHANGE = "orders_exchange"

# Track sent notifications (for observability)
notifications_sent: list[dict] = []


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


def on_inventory_reserved(ch, method, _props, body):
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        log.error("Malformed message, skipping: %s", body[:200])
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    order_id = event.get("order_id", "???")
    item = event.get("item", "???")
    qty = event.get("qty", "?")

    # "Send" the notification (simulated via log)
    notification = {
        "order_id": order_id,
        "message": f"✅ Your order for {qty}x {item} has been confirmed!",
        "sent_at": time.time(),
    }
    notifications_sent.append(notification)
    log.info("NOTIFICATION → %s | %s", order_id, notification["message"])

    ch.basic_ack(delivery_tag=method.delivery_tag)


# ── REST health / list endpoint ──────────────────────────────
def start_health_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/notifications":
                payload = json.dumps(notifications_sent).encode()
            else:
                payload = b'{"status":"ok","service":"notification_service"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *_): ...

    import threading
    t = threading.Thread(target=HTTPServer(("", 5003), H).serve_forever,
                         daemon=True)
    t.start()


# ── Main ─────────────────────────────────────────────────────
def main():
    start_health_server()
    conn = connect()
    ch = conn.channel()

    ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    ch.queue_declare(queue="inventory_reserved", durable=True)
    ch.queue_bind(queue="inventory_reserved", exchange=EXCHANGE,
                  routing_key="inventory.reserved")

    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue="inventory_reserved",
                     on_message_callback=on_inventory_reserved)

    log.info("Consuming inventory_reserved queue …")
    ch.start_consuming()


if __name__ == "__main__":
    main()
