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
