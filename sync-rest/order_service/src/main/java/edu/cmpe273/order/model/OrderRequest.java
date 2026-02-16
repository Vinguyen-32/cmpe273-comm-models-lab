package edu.cmpe273.order.model;

import java.util.List;

public record OrderRequest(String studentId, List<OrderItem> items) {}
