"""
Callback listener that runs alongside OrderService.
Consumes InventoryReserved / InventoryFailed events and updates
order status in the OrderService via its internal PATCH endpoint.
"""

import os, json, time, logging
import pika, requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [OrderCallback] %(message)s")
log = logging.getLogger(__name__)

RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", 5672))
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:5001")


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
    event = json.loads(body)
    order_id = event.get("order_id")
    log.info("InventoryReserved for %s", order_id)
    try:
        requests.patch(
            f"{ORDER_SERVICE_URL}/orders/{order_id}/status",
            json={"status": "RESERVED"},
            timeout=5,
        )
    except Exception as e:
        log.error("Failed to update order %s: %s", order_id, e)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def on_inventory_failed(ch, method, _props, body):
    event = json.loads(body)
    order_id = event.get("order_id")
    reason = event.get("reason", "unknown")
    log.info("InventoryFailed for %s: %s", order_id, reason)
    try:
        requests.patch(
            f"{ORDER_SERVICE_URL}/orders/{order_id}/status",
            json={"status": f"FAILED:{reason}"},
            timeout=5,
        )
    except Exception as e:
        log.error("Failed to update order %s: %s", order_id, e)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def main():
    conn = connect()
    ch = conn.channel()

    ch.exchange_declare(exchange="orders_exchange", exchange_type="topic",
                        durable=True)

    # Use separate queues so the callback listener gets its own copy
    # (the notification service also consumes inventory.reserved)
    ch.queue_declare(queue="order_callback_reserved", durable=True)
    ch.queue_declare(queue="order_callback_failed", durable=True)

    ch.queue_bind(queue="order_callback_reserved", exchange="orders_exchange",
                  routing_key="inventory.reserved")
    ch.queue_bind(queue="order_callback_failed", exchange="orders_exchange",
                  routing_key="inventory.failed")

    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue="order_callback_reserved",
                     on_message_callback=on_inventory_reserved)
    ch.basic_consume(queue="order_callback_failed",
                     on_message_callback=on_inventory_failed)

    log.info("Listening for inventory events …")
    ch.start_consuming()


if __name__ == "__main__":
    main()
