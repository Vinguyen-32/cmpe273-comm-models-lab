package edu.cmpe273.order.model;

import java.util.List;

public record ReserveRequest(String studentId, List<OrderItem> items) {}
