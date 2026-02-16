package edu.cmpe273.inventory.config;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

@Component
public class InjectionState {
    private final AtomicLong delayMs = new AtomicLong(0);
    private final AtomicBoolean forceFail = new AtomicBoolean(false);

    public long getDelayMs() {
        return delayMs.get();
    }

    public void setDelayMs(long delayMs) {
        this.delayMs.set(Math.max(delayMs, 0));
    }

    public boolean isForceFail() {
        return forceFail.get();
    }

    public void setForceFail(boolean forceFail) {
        this.forceFail.set(forceFail);
    }
}
