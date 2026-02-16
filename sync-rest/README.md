# Sync REST (Part A)

## Overview
Synchronous REST implementation of campus food ordering. OrderService calls Inventory and Notification services sequentially, blocking on each call.

## Services and endpoints
- OrderService: POST /order (port 8080)
- InventoryService: POST /reserve, POST /inject (port 8081)
- NotificationService: POST /send (port 8082)

## Prerequisites
- Docker
- Maven 3.9+
- Java 17+

## Build and run
```bash
docker compose -f sync-rest/docker-compose.yml up --build
```

## Tests (JUnit)
```bash
cd sync-rest/tests
mvn -q test
```

## Failure injection
InventoryService supports control endpoint:
- POST /inject

Example payload:
```json
{"delayMs":2000,"forceFail":false}
```

Delay adds latency to /order. Setting forceFail=true makes /reserve return 500.

## Example order request
```json
{"studentId":"s-100","items":[{"itemId":"burger","qty":1}]}
```

