from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai_qa_copilot_api.mock_order_api import (
    CREATED_ORDER_ID,
    DEFAULT_CUSTOMER_ID,
    GADGET_PRODUCT_ID,
    SEEDED_CONFIRMED_ORDER_ID,
    SEEDED_SHIPPED_ORDER_ID,
    SYNTHETIC_ORDER_API_VERSION,
    SYNTHETIC_TRACE_ID,
    WIDGET_PRODUCT_ID,
    app,
    create_mock_order_app,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_mock_order_app()) as test_client:
        yield test_client


def order_create_payload() -> dict[str, object]:
    return {
        "currency": "USD",
        "shippingAddress": {
            "line1": "42 Contract Lane",
            "city": "Example City",
            "countryCode": "US",
            "postalCode": "00001",
        },
        "items": [
            {
                "productId": str(WIDGET_PRODUCT_ID),
                "quantity": 2,
            }
        ],
    }


def assert_error(
    response_body: dict[str, object],
    *,
    error_code: str,
    message: str,
) -> None:
    assert response_body == {
        "errorCode": error_code,
        "message": message,
        "traceId": SYNTHETIC_TRACE_ID,
        "fieldErrors": [],
    }


def test_module_level_app_exposes_deployable_health_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "synthetic-mock-order-api",
        "version": SYNTHETIC_ORDER_API_VERSION,
    }


def test_openapi_exposes_the_synthetic_order_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()

    assert schema["info"]["title"] == "Synthetic Mock Order API"
    assert schema["info"]["version"] == SYNTHETIC_ORDER_API_VERSION
    assert {
        "/health",
        "/orders",
        "/orders/{order_id}",
        "/orders/{order_id}/cancel",
    }.issubset(schema["paths"])
    assert {"get", "post"}.issubset(schema["paths"]["/orders"])
    assert {"get", "patch"}.issubset(schema["paths"]["/orders/{order_id}"])
    assert "post" in schema["paths"]["/orders/{order_id}/cancel"]

    components = schema["components"]["schemas"]
    assert {
        "Order",
        "OrderCreate",
        "OrderPatch",
        "OrderPage",
        "CancelRequest",
        "ErrorResponse",
    }.issubset(components)


def test_list_orders_returns_deterministic_seeded_orders(client: TestClient) -> None:
    response = client.get("/orders")

    assert response.status_code == 200
    body = response.json()

    assert body["nextPageToken"] is None
    assert [item["id"] for item in body["items"]] == [
        str(SEEDED_SHIPPED_ORDER_ID),
        str(SEEDED_CONFIRMED_ORDER_ID),
    ]
    assert body["items"][0]["status"] == "SHIPPED"
    assert body["items"][1]["status"] == "CONFIRMED"


def test_get_seeded_order_returns_camel_case_contract_fields(
    client: TestClient,
) -> None:
    response = client.get(f"/orders/{SEEDED_CONFIRMED_ORDER_ID}")

    assert response.status_code == 200
    body = response.json()

    assert body["id"] == str(SEEDED_CONFIRMED_ORDER_ID)
    assert body["customerId"] == str(DEFAULT_CUSTOMER_ID)
    assert body["status"] == "CONFIRMED"
    assert body["currency"] == "USD"
    assert body["totalAmount"] == "49.90"
    assert body["version"] == 1
    assert body["items"] == [
        {
            "productId": str(GADGET_PRODUCT_ID),
            "sku": "GADGET-002",
            "quantity": 1,
            "unitPrice": 49.9,
            "lineTotal": 49.9,
        }
    ]
    assert body["createdAt"]
    assert body["updatedAt"]


def test_create_order_uses_seeded_catalog_and_default_customer(
    client: TestClient,
) -> None:
    response = client.post("/orders", json=order_create_payload())

    assert response.status_code == 201
    body = response.json()

    assert body["id"] == str(CREATED_ORDER_ID)
    assert body["customerId"] == str(DEFAULT_CUSTOMER_ID)
    assert body["status"] == "PENDING_PAYMENT"
    assert body["currency"] == "USD"
    assert body["totalAmount"] == "49.90"
    assert body["version"] == 1
    assert body["items"][0]["sku"] == "WIDGET-001"
    assert body["items"][0]["quantity"] == 2
    assert body["items"][0]["lineTotal"] == 49.9

    listed = client.get("/orders").json()
    assert listed["items"][0]["id"] == str(CREATED_ORDER_ID)


def test_create_order_preserves_explicit_customer_id(client: TestClient) -> None:
    payload = order_create_payload()
    payload["customerId"] = str(SEEDED_CONFIRMED_ORDER_ID)

    response = client.post("/orders", json=payload)

    assert response.status_code == 201
    assert response.json()["customerId"] == str(SEEDED_CONFIRMED_ORDER_ID)


def test_create_rejects_unknown_synthetic_product(client: TestClient) -> None:
    payload = order_create_payload()
    payload["items"] = [
        {
            "productId": "00000000-0000-0000-0000-00000000c099",
            "quantity": 1,
        }
    ]

    response = client.post("/orders", json=payload)

    assert response.status_code == 400
    assert_error(
        response.json(),
        error_code="ORDER_INPUT_INVALID",
        message="Unknown synthetic product",
    )


def test_second_create_is_rejected_to_keep_seeded_state_deterministic(
    client: TestClient,
) -> None:
    first_response = client.post("/orders", json=order_create_payload())
    second_response = client.post("/orders", json=order_create_payload())

    assert first_response.status_code == 201
    assert second_response.status_code == 400
    assert_error(
        second_response.json(),
        error_code="ORDER_INPUT_INVALID",
        message="Synthetic created-order identifier is already in use",
    )


def test_patch_updates_order_and_advances_its_version(client: TestClient) -> None:
    response = client.patch(
        f"/orders/{SEEDED_CONFIRMED_ORDER_ID}",
        json={
            "status": "PROCESSING",
            "shippingAddress": {
                "line1": "9 Updated Way",
                "city": "New City",
                "countryCode": "US",
                "postalCode": "10001",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "PROCESSING"
    assert body["shippingAddress"]["line1"] == "9 Updated Way"
    assert body["version"] == 2


def test_empty_patch_is_rejected(client: TestClient) -> None:
    response = client.patch(f"/orders/{SEEDED_CONFIRMED_ORDER_ID}", json={})

    assert response.status_code == 400
    assert_error(
        response.json(),
        error_code="ORDER_UPDATE_INVALID",
        message="At least one order field must be supplied",
    )


def test_cancel_confirmed_order_is_idempotent(client: TestClient) -> None:
    first_response = client.post(
        f"/orders/{SEEDED_CONFIRMED_ORDER_ID}/cancel",
        json={"reason": "Customer requested cancellation"},
    )
    second_response = client.post(
        f"/orders/{SEEDED_CONFIRMED_ORDER_ID}/cancel",
        json={"reason": "Ignored because order is already cancelled"},
    )

    assert first_response.status_code == 200
    assert first_response.json()["status"] == "CANCELED"
    assert (
        first_response.json()["cancellationReason"] == "Customer requested cancellation"
    )
    assert first_response.json()["version"] == 2

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "CANCELED"
    assert (
        second_response.json()["cancellationReason"]
        == "Customer requested cancellation"
    )
    assert second_response.json()["version"] == 2


def test_shipped_order_cannot_be_cancelled(client: TestClient) -> None:
    response = client.post(f"/orders/{SEEDED_SHIPPED_ORDER_ID}/cancel")

    assert response.status_code == 409
    assert_error(
        response.json(),
        error_code="ORDER_CANCELLATION_INELIGIBLE",
        message="Order is not eligible for cancellation",
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/orders/00000000-0000-0000-0000-00000000d001"),
        ("patch", "/orders/00000000-0000-0000-0000-00000000d001"),
        ("post", "/orders/00000000-0000-0000-0000-00000000d001/cancel"),
    ],
)
def test_unknown_order_returns_documented_error(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path, json={} if method == "patch" else None)

    assert response.status_code == 404
    assert_error(
        response.json(),
        error_code="ORDER_NOT_FOUND",
        message="The requested order was not found.",
    )


def test_runtime_failure_is_an_explicit_opt_in_controlled_defect(
    client: TestClient,
) -> None:
    response = client.get(
        f"/orders/{SEEDED_CONFIRMED_ORDER_ID}",
        headers={"X-Mock-Scenario": "runtime-failure"},
    )

    assert response.status_code == 503
    assert_error(
        response.json(),
        error_code="SYNTHETIC_RUNTIME_FAILURE",
        message="Controlled synthetic runtime failure",
    )


def test_missing_version_is_an_explicit_opt_in_controlled_defect(
    client: TestClient,
) -> None:
    normal_response = client.get(f"/orders/{SEEDED_CONFIRMED_ORDER_ID}")
    defect_response = client.get(
        f"/orders/{SEEDED_CONFIRMED_ORDER_ID}",
        headers={"X-Mock-Scenario": "missing-version"},
    )

    assert normal_response.status_code == 200
    assert normal_response.json()["version"] == 1

    assert defect_response.status_code == 200
    assert "version" not in defect_response.json()
