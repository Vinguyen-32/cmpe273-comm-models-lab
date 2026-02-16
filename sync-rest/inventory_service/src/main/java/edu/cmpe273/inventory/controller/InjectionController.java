package edu.cmpe273.inventory.controller;

import edu.cmpe273.inventory.config.InjectionState;
import edu.cmpe273.inventory.model.InjectRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class InjectionController {
    private final InjectionState state;

    public InjectionController(InjectionState state) {
        this.state = state;
    }

    @PostMapping("/inject")
    public ResponseEntity<InjectRequest> inject(@RequestBody InjectRequest request) {
        state.setDelayMs(request.delayMs());
        state.setForceFail(request.forceFail());
        return ResponseEntity.ok(new InjectRequest(state.getDelayMs(), state.isForceFail()));
    }
}
