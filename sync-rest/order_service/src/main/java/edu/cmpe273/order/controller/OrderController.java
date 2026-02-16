package edu.cmpe273.order.controller;

import edu.cmpe273.order.model.NotificationRequest;
import edu.cmpe273.order.model.NotificationResponse;
import edu.cmpe273.order.model.OrderRequest;
import edu.cmpe273.order.model.OrderResponse;
import edu.cmpe273.order.model.ReserveRequest;
import edu.cmpe273.order.model.ReserveResponse;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

@RestController
public class OrderController {
    private final RestTemplate restTemplate;
    private final String inventoryUrl;
    private final String notificationUrl;

    public OrderController(RestTemplate restTemplate,
                           @Value("${inventory.url}") String inventoryUrl,
                           @Value("${notification.url}") String notificationUrl) {
        this.restTemplate = restTemplate;
        this.inventoryUrl = inventoryUrl;
        this.notificationUrl = notificationUrl;
    }

    @PostMapping("/order")
    public ResponseEntity<OrderResponse> placeOrder(@RequestBody OrderRequest request) {
        String orderId = UUID.randomUUID().toString();
        ReserveRequest reserveRequest = new ReserveRequest(request.studentId(), request.items());

        ResponseEntity<ReserveResponse> reserveResponse;
        try {
            reserveResponse = restTemplate.postForEntity(
                inventoryUrl + "/reserve",
                reserveRequest,
                ReserveResponse.class
            );
        } catch (ResourceAccessException ex) {
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT)
                .body(new OrderResponse(orderId, "FAILED", "Inventory timeout"));
        } catch (RestClientResponseException ex) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                .body(new OrderResponse(orderId, "FAILED", "Inventory error"));
        }

        ReserveResponse reserveBody = reserveResponse.getBody();
        if (!reserveResponse.getStatusCode().is2xxSuccessful()
            || reserveBody == null
            || !reserveBody.reserved()) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                .body(new OrderResponse(orderId, "FAILED", "Reserve rejected"));
        }

        NotificationRequest notificationRequest = new NotificationRequest(orderId, request.studentId());
        try {
            ResponseEntity<NotificationResponse> notifyResponse = restTemplate.postForEntity(
                notificationUrl + "/send",
                notificationRequest,
                NotificationResponse.class
            );

            if (!notifyResponse.getStatusCode().is2xxSuccessful()) {
                return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .body(new OrderResponse(orderId, "FAILED", "Notification error"));
            }
        } catch (RestClientResponseException ex) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                .body(new OrderResponse(orderId, "FAILED", "Notification error"));
        }

        return ResponseEntity.ok(new OrderResponse(orderId, "PLACED", "Order accepted"));
    }
}
