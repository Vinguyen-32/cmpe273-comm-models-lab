"""
Shared ID generation utility used across all services.
Generates short, human-readable unique order IDs.
"""

import uuid
import time


def generate_order_id() -> str:
    """Generate a unique order ID with a readable prefix."""
    ts = int(time.time() * 1000) % 1_000_000
    short = uuid.uuid4().hex[:6]
    return f"ORD-{ts}-{short}"


if __name__ == "__main__":
    for _ in range(5):
        print(generate_order_id())
