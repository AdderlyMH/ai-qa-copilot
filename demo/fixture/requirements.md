# Demo order service requirements

Synthetic content authored for the guest demo of the AI Quality Engineering
Copilot. It describes a fictional order service and is not a real
specification. Some requirements below are deliberately flawed: vague,
incomplete or contradictory.

REQ-ORD-001: Given a valid order request with one to ten units per item, when the client submits it, then the service must respond with status 201 and set the order status to PENDING_PAYMENT.
REQ-ORD-002: The service should accept orders quickly and return a reasonable error message for bad input.
REQ-ORD-003: A customer may update the shipping address of an order.
REQ-ORD-004: Order cancellation must be available as needed.
REQ-ORD-005: A shipped order must be cancellable.
REQ-ORD-006: A shipped order must not be cancellable.
REQ-ORD-007: The order list must load fast for large accounts.
REQ-ORD-008: Admins can approve a pending order by changing its status.
