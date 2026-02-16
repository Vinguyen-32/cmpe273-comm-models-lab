package edu.cmpe273.notification.controller;

import edu.cmpe273.notification.model.NotificationRequest;
import edu.cmpe273.notification.model.NotificationResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class NotificationController {
    @PostMapping("/send")
    public ResponseEntity<NotificationResponse> send(@RequestBody NotificationRequest request) {
        return ResponseEntity.ok(new NotificationResponse(true));
    }
}
