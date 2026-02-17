# CMPE 273 - Communication Models Lab

Campus food ordering workflow implemented using three communication models:
- **Part A**: Synchronous REST
- **Part B**: Async Messaging with RabbitMQ
- **Part C**: Streaming with Kafka

---

# Part A: Synchronous REST

## Build and Run

```bash
docker compose -f sync-rest/docker-compose.yml up --build
```

## Run Tests

```bash
cd sync-rest/tests
mvn clean test
```

---

## Latency Table

| Scenario | Avg Latency (ms) | P95 (ms) |
|----------|------------------|----------|
| Baseline | 11.95 | 19 |
| Inventory 2s delay | 2085.8 | 2301 |
| Inventory failure | HTTP 502 | - |

---

## Reasoning

**Why does delay propagate?**  
OrderService makes synchronous blocking calls. It waits for Inventory to respond before calling Notification. A 2s delay in Inventory adds ~2s to the total response time.

**Why does failure return 502?**  
When Inventory fails, OrderService catches the error and returns HTTP 502 (Bad Gateway). Notification is not called because the chain stops at the failed step.
