package edu.cmpe273.inventory.model;

import java.util.List;

public record ReserveRequest(String studentId, List<OrderItem> items) {}
