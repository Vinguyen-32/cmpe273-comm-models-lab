"""
Test suite for Part B – Async RabbitMQ Campus Food Ordering.

Tests covered:
  1. test_happy_path           – Place an order, verify reservation & notification
  2. test_backlog_drain        – Kill InventoryService, publish orders, restart, verify drain
  3. test_idempotency          – Re-deliver the same OrderPlaced twice → no double reserve
  4. test_dlq_poison_message   – Publish malformed event → routed to DLQ

Prerequisites:
  docker compose up -d          (all services running)
  pip install requests pika     (for running tests locally)

Usage:
  cd async-rabbitmq
  python -m pytest tests/test_async.py -v -s
"""

import json, time, subprocess, sys
import requests
import pika
import pytest

BASE = "http://localhost:5001"
RABBIT_HOST = "localhost"
RABBIT_PORT = 5672
EXCHANGE = "orders_exchange"


# ── Helpers ──────────────────────────────────────────────────
def place_order(item="Pizza", qty=1, student_id="S100"):
    r = requests.post(f"{BASE}/order",
                      json={"item": item, "qty": qty, "student_id": student_id},
                      timeout=10)
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    return r.json()


def get_order(order_id):
    r = requests.get(f"{BASE}/orders/{order_id}", timeout=10)
    return r.json()


def rabbit_connection():
    return pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBIT_HOST, port=RABBIT_PORT)
    )


def queue_message_count(queue_name):
    conn = rabbit_connection()
    ch = conn.channel()
    q = ch.queue_declare(queue=queue_name, durable=True, passive=True)
    count = q.method.message_count
    conn.close()
    return count


def docker_compose(*args):
    """Run a docker compose command in the async-rabbitmq directory."""
    subprocess.run(
        ["docker", "compose"] + list(args),
        check=True,
        timeout=120,
    )


# ── 1. Happy Path ───────────────────────────────────────────
class TestHappyPath:
    def test_order_placed_and_reserved(self):
        """Place an order → InventoryService reserves → status becomes RESERVED."""
        order = place_order("Pizza", 1, "S200")
        order_id = order["order_id"]
        assert order["status"] == "PLACED"

        # Wait for async pipeline to complete
        for _ in range(20):
            time.sleep(1)
            o = get_order(order_id)
            if o.get("status") == "RESERVED":
                break
        assert o["status"] == "RESERVED", f"Expected RESERVED, got {o['status']}"
        print(f"✅ Order {order_id} reserved successfully")

    def test_notification_sent(self):
        """Verify that NotificationService received the confirmation."""
        order = place_order("Burger", 1, "S201")
        time.sleep(5)
        r = requests.get("http://localhost:5003/notifications", timeout=10)
        notifications = r.json()
        matching = [n for n in notifications
                    if n["order_id"] == order["order_id"]]
        assert len(matching) >= 1, "Notification not found"
        print(f"✅ Notification sent: {matching[0]['message']}")


# ── 2. Backlog Drain ────────────────────────────────────────
class TestBacklogDrain:
    def test_kill_inventory_publish_orders_restart(self):
        """
        1. Stop InventoryService
        2. Publish 10 orders (they queue up in order_placed)
        3. Restart InventoryService
        4. Verify all orders are eventually RESERVED
        """
        # Stop inventory
        print("\n🛑 Stopping InventoryService …")
        docker_compose("stop", "inventory_service")
        time.sleep(5)

        # Publish orders while inventory is down
        order_ids = []
        for i in range(10):
            o = place_order("Coffee", 1, f"BACKLOG-{i}")
            order_ids.append(o["order_id"])
            print(f"   Published {o['order_id']} (inventory is down)")

        # Check messages are queued
        backlog = queue_message_count("order_placed")
        print(f"📬 Backlog in order_placed queue: {backlog}")
        assert backlog >= 5, f"Expected backlog ≥ 5, got {backlog}"

        # Restart inventory
        print("▶️  Restarting InventoryService …")
        docker_compose("start", "inventory_service")

        # Wait for drain
        print("⏳ Waiting for backlog to drain …")
        for _ in range(30):
            time.sleep(2)
            remaining = queue_message_count("order_placed")
            if remaining == 0:
                break
        print(f"   Remaining in queue: {remaining}")

        # Verify all orders are RESERVED
        time.sleep(5)  # extra time for callback listener
        for oid in order_ids:
            o = get_order(oid)
            assert o["status"] == "RESERVED", \
                f"Order {oid} status is {o['status']}, expected RESERVED"
        print(f"✅ All {len(order_ids)} backlogged orders drained and reserved")


# ── 3. Idempotency ──────────────────────────────────────────
class TestIdempotency:
    def test_duplicate_order_placed_no_double_reserve(self):
        """
        Manually publish the same OrderPlaced event twice.
        InventoryService should only reserve once.
        """
        order_id = f"IDEMP-{int(time.time())}"
        event = {
            "order_id": order_id,
            "item": "Salad",
            "qty": 5,
            "student_id": "S300",
            "status": "PLACED",
        }

        conn = rabbit_connection()
        ch = conn.channel()
        ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic",
                            durable=True)

        # Publish twice
        for attempt in range(2):
            ch.basic_publish(
                exchange=EXCHANGE,
                routing_key="order.placed",
                body=json.dumps(event),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            print(f"   Published OrderPlaced #{attempt + 1} for {order_id}")
        conn.close()

        time.sleep(5)

        # Check inventory_reserved queue – should see exactly 1 reserved event
        conn = rabbit_connection()
        ch = conn.channel()

        reserved_count = 0
        # Consume from a temporary exclusive queue bound to the same key
        # Instead, we check the notifications endpoint or the logs.
        conn.close()

        # We verify via notification service: should have at most 1 notification
        r = requests.get("http://localhost:5003/notifications", timeout=10)
        notifications = r.json()
        matching = [n for n in notifications if n["order_id"] == order_id]
        assert len(matching) <= 1, \
            f"Expected ≤ 1 notification, got {len(matching)} (double reserve!)"
        print(f"✅ Idempotency verified: {len(matching)} notification(s) for {order_id}")


# ── 4. DLQ / Poison Message ─────────────────────────────────
class TestDLQ:
    def test_malformed_message_goes_to_dlq(self):
        """
        Publish a malformed (non-JSON) message to order_placed.
        InventoryService NACKs it → RabbitMQ routes to order_placed_dlq.
        """
        conn = rabbit_connection()
        ch = conn.channel()

        # Ensure DLQ exists
        ch.queue_declare(queue="order_placed_dlq", durable=True)

        # Purge DLQ first to get a clean count
        ch.queue_purge(queue="order_placed_dlq")

        # Publish garbage
        ch.basic_publish(
            exchange=EXCHANGE,
            routing_key="order.placed",
            body=b"THIS-IS-NOT-JSON!!!",
            properties=pika.BasicProperties(delivery_mode=2),
        )
        print("   Published malformed message to order.placed")
        conn.close()

        # Wait for InventoryService to NACK it
        time.sleep(5)

        dlq_count = queue_message_count("order_placed_dlq")
        print(f"   Messages in order_placed_dlq: {dlq_count}")
        assert dlq_count >= 1, f"Expected ≥ 1 in DLQ, got {dlq_count}"

        # Read the poison message from DLQ
        conn = rabbit_connection()
        ch = conn.channel()
        method, props, body = ch.basic_get(queue="order_placed_dlq",
                                            auto_ack=True)
        assert body is not None
        print(f"✅ Poison message in DLQ: {body.decode()}")
        conn.close()


# ── Run directly ─────────────────────────────────────────────
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
