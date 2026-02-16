package edu.cmpe273.tests;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Arrays;
import org.junit.jupiter.api.Test;

public class OrderLatencyTest {
    private static final HttpClient CLIENT = HttpClient.newHttpClient();
    private static final String ORDER_URL =
        System.getenv().getOrDefault("ORDER_URL", "http://localhost:8080/order");
    private static final String INVENTORY_URL =
        System.getenv().getOrDefault("INVENTORY_URL", "http://localhost:8081");

    @Test
    void baselineLatency() throws Exception {
        waitReady();
        inject(0, false);
        LatencyResult result = runOrders(20);
        System.out.println("Baseline avgMs=" + result.avgMs + " p95Ms=" + result.p95Ms);
        assertTrue(result.successCount > 0);
    }

    @Test
    void delayedInventoryLatency() throws Exception {
        waitReady();
        inject(2000, false);
        Thread.sleep(500);
        LatencyResult result = runOrders(5);
        System.out.println("Delay avgMs=" + result.avgMs + " p95Ms=" + result.p95Ms);
        assertTrue(result.avgMs >= 1900, "avgMs was " + result.avgMs + ", expected >= 1900");
    }

    @Test
    void inventoryFailure() throws Exception {
        waitReady();
        inject(0, true);
        Thread.sleep(200);
        HttpResponse<String> response = postJson(ORDER_URL, orderPayload());
        System.out.println("Failure status=" + response.statusCode());
        assertTrue(response.statusCode() >= 500);
        inject(0, false);
    }

    private static void waitReady() throws Exception {
        Exception lastEx = null;
        for (int i = 0; i < 15; i++) {
            try {
                HttpResponse<String> resp = postJson(INVENTORY_URL + "/inject", "{\"delayMs\":0,\"forceFail\":false}");
                if (resp.statusCode() == 200) {
                    System.out.println("Services ready");
                    return;
                }
                System.out.println("Attempt " + (i + 1) + ": Got status " + resp.statusCode());
            } catch (Exception ex) {
                lastEx = ex;
                System.out.println("Attempt " + (i + 1) + ": " + ex.getClass().getSimpleName() + " - " + ex.getMessage());
                Thread.sleep(2000);
            }
        }
        String msg = "Services unreachable. Last error: " + (lastEx != null ? lastEx.getMessage() : "unknown");
        throw new RuntimeException(msg);
    }

    private static void inject(long delayMs, boolean forceFail) throws Exception {
        String json = "{\"delayMs\":" + delayMs + ",\"forceFail\":" + forceFail + "}";
        HttpResponse<String> response = postJson(INVENTORY_URL + "/inject", json);
        if (response.statusCode() != 200) {
            throw new RuntimeException("Inject failed with status " + response.statusCode());
        }
        System.out.println("Injected delayMs=" + delayMs + " forceFail=" + forceFail);
    }

    private static LatencyResult runOrders(int count) throws Exception {
        long[] durations = new long[count];
        int success = 0;
        for (int i = 0; i < count; i++) {
            long start = System.nanoTime();
            HttpResponse<String> response = postJson(ORDER_URL, orderPayload());
            long end = System.nanoTime();
            durations[i] = Duration.ofNanos(end - start).toMillis();
            if (response.statusCode() == 200) {
                success++;
            }
        }

        double avg = Arrays.stream(durations).average().orElse(0);
        Arrays.sort(durations);
        int p95Index = (int) Math.ceil(count * 0.95) - 1;
        long p95 = durations[Math.max(p95Index, 0)];
        return new LatencyResult(avg, p95, success);
    }

    private static HttpResponse<String> postJson(String url, String json) throws Exception {
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json))
            .timeout(Duration.ofSeconds(10))
            .build();
        return CLIENT.send(request, HttpResponse.BodyHandlers.ofString());
    }

    private static String orderPayload() {
        return "{\"studentId\":\"s-100\",\"items\":[{\"itemId\":\"burger\",\"qty\":1}]}";
    }

    private record LatencyResult(double avgMs, long p95Ms, int successCount) {}
}
