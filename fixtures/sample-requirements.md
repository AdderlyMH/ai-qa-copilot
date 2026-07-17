# Acme Commerce Order Management Requirements

**Fixture ID:** OMR-BASE-001  
**Version:** 1.0  
**Classification:** Synthetic evaluation data  
**Intended use:** Requirement analysis, OpenAPI comparison, test generation, traceability, and safe execution planning

> Evaluation note: This fixture intentionally contains ambiguities, contradictions, omissions, and terminology mismatches. They are not marked inline because identifying them is part of the benchmark. Do not treat this document as a production specification.

## 1. Product context

Acme Commerce provides an order-management API for customers, support agents, and administrators. Customers authenticate, browse products, create orders, inspect their own orders, modify eligible orders, and cancel eligible orders. Support agents can assist customers. Administrators manage operational functions.

The initial release supports USD and other standard currencies. Orders should be processed immediately and should provide clear errors when a request cannot be completed.

## 2. Roles

### Customer

A registered person who can manage a customer profile and place orders.

### Support agent

An Acme employee who may inspect customer orders to resolve support cases.

### Administrator

An Acme employee with elevated operational permissions.

The exact permissions inherited by each role are managed by the identity platform.

## 3. Glossary

| Term | Meaning |
|---|---|
| Eligible order | An order that can still be changed or cancelled |
| Processing | The point at which fulfillment work has begun |
| Available product | A product that can currently be ordered |
| Immediate | Without unnecessary delay |
| Correlation ID | Identifier used to trace one request across services |

## 4. Authentication requirements

### REQ-AUTH-001 — Obtain access token

A registered user shall be able to exchange valid credentials for a bearer access token.

#### Acceptance criteria

1. Valid credentials return an access token.
2. Invalid credentials return `401 Unauthorized`.
3. The access token expires after 60 minutes.
4. The response identifies the user role.
5. Authentication failures do not reveal whether an email address is registered.

### REQ-AUTH-002 — Protected operations

All operations other than token creation and product search require a valid bearer token.

#### Acceptance criteria

1. A missing token returns `401 Unauthorized`.
2. An expired or invalid token returns `401 Unauthorized`.
3. A token with insufficient permissions returns `403 Forbidden`.

## 5. Customer requirements

### REQ-CUST-001 — Create customer profile

A registered user shall create a customer profile before placing an order.

#### Acceptance criteria

1. The request includes `email`, `displayName`, and `defaultShippingAddress`.
2. `email` is unique and uses a valid email format.
3. `displayName` contains between 1 and 100 visible characters.
4. A duplicate email returns `409 Conflict`.
5. A successful request returns `201 Created` and the customer identifier.

### REQ-CUST-002 — Retrieve customer profile

A customer shall retrieve only their own customer profile. Support agents may retrieve a customer profile when working on an active support case.

#### Acceptance criteria

1. The owner receives `200 OK`.
2. A different customer receives `403 Forbidden`.
3. A missing customer returns `404 Not Found`.
4. Support access is recorded in the audit trail.

## 6. Product requirements

### REQ-PROD-001 — Search products

Any user shall search available products without authentication.

#### Acceptance criteria

1. Results may be filtered by free-text query and availability.
2. Results are paginated.
3. `limit` defaults to 20 and supports values from 1 through 100.
4. An invalid page token returns `400 Bad Request`.
5. Only available products are returned when `available=true`.

## 7. Order creation requirements

### REQ-ORDER-001 — Create order

An authenticated customer shall create an order containing one or more available products.

#### Acceptance criteria

1. The request includes `customerId`, `currency`, `shippingAddress`, and at least one item.
2. Each item includes `productId` and a whole-number `quantity` from 1 through 20.
3. `currency` is a valid ISO 4217 currency code.
4. The authenticated customer must own the supplied `customerId`.
5. The service calculates item prices and the total; client-supplied prices are ignored.
6. A successful request returns `201 Created`.
7. The initial order status is `PENDING_PAYMENT`.
8. An unavailable product returns `409 Conflict`.
9. Invalid input returns `400 Bad Request` with field-level details.

### REQ-ORDER-002 — Idempotent order creation

Order creation shall be idempotent when the client supplies an `Idempotency-Key` header.

#### Acceptance criteria

1. `Idempotency-Key` is required for every order-creation request.
2. Repeating an identical request with the same key returns the original order and does not reserve inventory twice.
3. Reusing the key with a materially different request returns `409 Conflict`.
4. Keys remain valid for 24 hours.
5. The response indicates whether it is the original or replayed result.

### REQ-ORDER-003 — Order status lifecycle

An order follows this lifecycle:

```text
PENDING_PAYMENT → CONFIRMED → PROCESSING → SHIPPED → DELIVERED
```

An eligible order may transition to `CANCELLED`.

#### Acceptance criteria

1. Payment authorization changes `PENDING_PAYMENT` to `CONFIRMED`.
2. Fulfillment changes `CONFIRMED` to `PROCESSING`.
3. A shipped or delivered order cannot return to an earlier status.
4. Invalid transitions return `409 Conflict`.
5. Every transition records timestamp, actor, previous status, and new status.

### REQ-ORDER-004 — Cancel order

A customer shall cancel their own eligible order within 15 minutes of creation.

#### Acceptance criteria

1. Orders in `PENDING_PAYMENT` or `CONFIRMED` are eligible.
2. Orders in `PROCESSING`, `SHIPPED`, or `DELIVERED` are not eligible.
3. Cancellation changes the status to `CANCELLED`.
4. Cancellation releases any inventory reservation.
5. An ineligible cancellation returns `409 Conflict`.
6. Cancelling an already cancelled order returns the existing cancelled order without a second side effect.

### REQ-ORDER-005 — Customer cancellation window

Customers may cancel an order for up to 30 minutes after the order is confirmed, provided it has not shipped.

#### Acceptance criteria

1. The cancellation window begins when payment is confirmed.
2. A support agent may override the window for a customer-service reason.
3. An administrator may cancel any order that has not been delivered.
4. The response includes the cancellation reason and actor.

### REQ-ORDER-006 — Update shipping address

A customer may update the shipping address until processing begins.

#### Acceptance criteria

1. The customer owns the order.
2. The replacement address is valid.
3. The change occurs before processing begins.
4. An ineligible update returns `409 Conflict`.
5. The response returns the updated order.

### REQ-ORDER-007 — Concurrent updates

Order updates shall not silently overwrite a newer version.

#### Acceptance criteria

1. Every order representation contains a version value.
2. An update supplies the version previously read by the client.
3. A stale version returns `409 Conflict`.
4. The conflict response includes the current version.

## 8. Payment and inventory requirements

### REQ-PAY-001 — Authorize payment

A customer shall authorize payment for an order in `PENDING_PAYMENT` status.

#### Acceptance criteria

1. The authorization amount equals the server-calculated order total.
2. A successful authorization changes the order to `CONFIRMED`.
3. A declined authorization leaves the order in `PENDING_PAYMENT`.
4. Repeated authorization for a confirmed order does not create a second charge.
5. Provider decline information is sanitized before it is returned.

### REQ-INV-001 — Reserve inventory

Inventory shall be reserved for each order before it is confirmed.

#### Acceptance criteria

1. Reservation is atomic across all order items.
2. If any item lacks inventory, no item remains reserved.
3. A cancellation releases inventory immediately.
4. A reservation expires when payment is not authorized in time.
5. Concurrent orders cannot reserve more units than are available.

## 9. Query and authorization requirements

### REQ-ORDER-008 — Retrieve order

A customer shall retrieve their own order by order identifier. Support agents may retrieve any order associated with an active support case.

#### Acceptance criteria

1. The owner receives `200 OK`.
2. A different customer receives `403 Forbidden`.
3. A missing order returns `404 Not Found`.
4. Support access records the support-case identifier.

### REQ-ORDER-009 — List orders

A customer shall list only their own orders. Support agents may list orders for a specified customer.

#### Acceptance criteria

1. Results may be filtered by status and creation date.
2. Results are sorted newest first by default.
3. `limit` defaults to 20 and supports values from 1 through 100.
4. Pagination does not repeat or skip records when no orders change.
5. A customer cannot supply another customer’s identifier.

### REQ-AUTHZ-001 — Role enforcement

The API shall enforce customer, support-agent, and administrator permissions consistently.

#### Acceptance criteria

1. Customers access only their own customer and order resources.
2. Support access requires an active support case.
3. Administrator actions are restricted to operational tasks.
4. A denied action returns `403 Forbidden` and is audited.
5. The API never relies only on a client-supplied role field.

## 10. Refund requirement

### REQ-REFUND-001 — Refund cancelled order

When a paid order is cancelled, the customer shall be able to request a refund.

#### Acceptance criteria

1. Only a paid and cancelled order is eligible.
2. The refund uses the original payment method.
3. The customer receives a refund status.
4. Duplicate refund requests do not create duplicate refunds.
5. Refunds should be completed promptly.

## 11. Error, traceability, and privacy requirements

### REQ-ERR-001 — Error response format

Every non-success response shall use this shape:

```json
{
  "code": "ORDER_NOT_FOUND",
  "message": "The order was not found.",
  "correlationId": "a traceable identifier",
  "fieldErrors": []
}
```

#### Acceptance criteria

1. `code`, `message`, and `correlationId` are always present.
2. Validation errors include `fieldErrors`.
3. Internal stack traces and provider secrets are never returned.
4. The same error condition uses the same code across endpoints.

### REQ-TRACE-001 — Correlation identifier

Every request and response shall support an `X-Correlation-ID` header.

#### Acceptance criteria

1. A valid client-supplied identifier is preserved.
2. The service generates an identifier when none is supplied.
3. The identifier appears in logs and error responses.
4. Invalid identifiers return `400 Bad Request`.

### REQ-PII-001 — Sensitive-data handling

Customer email, shipping address, payment references, and access tokens shall be protected.

#### Acceptance criteria

1. Tokens are never returned in logs or order responses.
2. Support views mask unnecessary personal information.
3. Error messages do not echo payment details.
4. Audit records identify access without copying full sensitive payloads.

## 12. Operational requirements

### REQ-PERF-001 — Response time

The service shall respond immediately to ordinary read operations.

#### Acceptance criteria

1. Product search and order retrieval complete within 2 seconds under normal load.
2. Order creation completes within 5 seconds, excluding external payment-provider delay.
3. A timeout returns a consistent error.

### REQ-RATE-001 — Rate limiting

The API shall protect itself from excessive requests.

#### Acceptance criteria

1. Authenticated users may make 100 requests per minute.
2. Exceeding the limit returns `429 Too Many Requests`.
3. The response indicates when the client may retry.
4. Rate-limit errors use the standard error response.

## 13. Open questions recorded by the product team

- Which currencies will be enabled at launch?
- How is an active support case verified?
- What event precisely means processing has begun?
- When does an unpaid inventory reservation expire?
- What refund timeframe qualifies as prompt?
- Are administrator cancellation rights intended to override payment and fulfillment rules?
