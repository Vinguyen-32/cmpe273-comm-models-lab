"""
OrderService – Accepts food orders via REST, persists locally,
and publishes an OrderPlaced event to RabbitMQ.
"""

import os, json, time, logging
from flask import Flask, request, jsonify
import pika

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [OrderService] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", 5672))
EXCHANGE = "orders_exchange"

# ── In-memory order store ────────────────────────────────────
orders: dict = {}
_order_counter = 0


def _next_order_id() -> str:
    global _order_counter
    _order_counter += 1
    ts = int(time.time() * 1000) % 1_000_000
    return f"ORD-{ts}-{_order_counter:04d}"


# ── RabbitMQ helpers ─────────────────────────────────────────
def _get_connection():
    """Create a blocking connection with retries."""
    for attempt in range(10):
        try:
            return pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBIT_HOST,
                    port=RABBIT_PORT,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
            )
        except pika.exceptions.AMQPConnectionError:
            log.warning("RabbitMQ not ready, retry %d/10 …", attempt + 1)
            time.sleep(3)
    raise RuntimeError("Cannot connect to RabbitMQ")


def publish_event(routing_key: str, body: dict):
    """Publish a JSON event to the orders exchange."""
    conn = _get_connection()
    ch = conn.channel()
    ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    ch.basic_publish(
        exchange=EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(body),
        properties=pika.BasicProperties(
            delivery_mode=2,  # persistent
            content_type="application/json",
        ),
    )
    conn.close()
    log.info("Published %s → %s", routing_key, body.get("order_id"))


# ── REST endpoints ───────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok", service="order_service")


@app.route("/order", methods=["POST"])
def create_order():
    """
    POST /order
    Body: { "item": "Pizza", "qty": 2, "student_id": "S123" }
    """
    data = request.get_json(force=True)
    item = data.get("item")
    qty = data.get("qty", 1)
    student_id = data.get("student_id", "anonymous")

    if not item:
        return jsonify(error="item is required"), 400

    order_id = _next_order_id()
    order = {
        "order_id": order_id,
        "item": item,
        "qty": qty,
        "student_id": student_id,
        "status": "PLACED",
        "created_at": time.time(),
    }
    orders[order_id] = order
    log.info("Order created: %s", order_id)

    # Publish OrderPlaced event
    publish_event("order.placed", order)

    return jsonify(order), 201


@app.route("/orders", methods=["GET"])
def list_orders():
    return jsonify(list(orders.values()))


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    order = orders.get(order_id)
    if not order:
        return jsonify(error="not found"), 404
    return jsonify(order)


@app.route("/orders/<order_id>/status", methods=["PATCH"])
def update_status(order_id):
    """Called internally by the callback listener to update order status."""
    data = request.get_json(force=True)
    order = orders.get(order_id)
    if not order:
        return jsonify(error="not found"), 404
    order["status"] = data.get("status", order["status"])
    log.info("Order %s → %s", order_id, order["status"])
    return jsonify(order)


# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
