package edu.cmpe273.inventory.controller;

import edu.cmpe273.inventory.config.InjectionState;
import edu.cmpe273.inventory.model.ReserveRequest;
import edu.cmpe273.inventory.model.ReserveResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InventoryController {
    private final InjectionState state;

    public InventoryController(InjectionState state) {
        this.state = state;
    }

    @PostMapping("/reserve")
    public ResponseEntity<ReserveResponse> reserve(@RequestBody ReserveRequest request) {
        if (state.isForceFail()) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(new ReserveResponse(false, "Injected failure"));
        }

        long delayMs = state.getDelayMs();
        if (delayMs > 0) {
            try {
                Thread.sleep(delayMs);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(new ReserveResponse(false, "Interrupted"));
            }
        }

        return ResponseEntity.ok(new ReserveResponse(true, "Reserved"));
    }
}
