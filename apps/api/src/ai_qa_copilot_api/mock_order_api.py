"""Seeded synthetic order API for controlled execution development."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Final
from uuid import UUID

from fastapi import FastAPI, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


SYNTHETIC_ORDER_API_VERSION: Final = "synthetic-order-api/v1"
SYNTHETIC_TRACE_ID: Final = "01J0SYNTHETICORDERTRACE000001"
SEEDED_TIMESTAMP: Final = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)

DEFAULT_CUSTOMER_ID: Final = UUID("00000000-0000-0000-0000-00000000b001")
SEEDED_CONFIRMED_ORDER_ID: Final = UUID("00000000-0000-0000-0000-00000000b101")
SEEDED_SHIPPED_ORDER_ID: Final = UUID("00000000-0000-0000-0000-00000000b102")
CREATED_ORDER_ID: Final = UUID("00000000-0000-0000-0000-00000000b103")

WIDGET_PRODUCT_ID: Final = UUID("00000000-0000-0000-0000-00000000c001")
GADGET_PRODUCT_ID: Final = UUID("00000000-0000-0000-0000-00000000c002")


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    """Base model for the synthetic API's documented JSON contract."""

    model_config = ConfigDict(
        alias_generator=_camel_case,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class OrderStatus(StrEnum):
    """Statuses intentionally aligned with the sample OpenAPI contract."""

    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"


class MockScenario(StrEnum):
    """Explicit opt-in runtime defects; normal requests use ``CONTRACT``."""

    CONTRACT = "contract"
    RUNTIME_FAILURE = "runtime-failure"
    MISSING_VERSION = "missing-version"


class Address(ContractModel):
    line_1: Annotated[str, Field(min_length=1, max_length=200)]
    city: Annotated[str, Field(min_length=1, max_length=100)]
    country_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    postal_code: Annotated[str, Field(min_length=1, max_length=20)]
    line_2: Annotated[str | None, Field(max_length=200)] = None
    region: Annotated[str | None, Field(max_length=100)] = None


class OrderItemRequest(ContractModel):
    product_id: UUID
    quantity: Annotated[int, Field(ge=1, le=10)]


class OrderCreate(ContractModel):
    currency: Annotated[str, Field(pattern=r"^(USD|EUR)$")]
    shipping_address: Address
    items: Annotated[tuple[OrderItemRequest, ...], Field(min_length=1, max_length=50)]
    customer_id: UUID | None = None


class OrderPatch(ContractModel):
    shipping_address: Address | None = None
    status: OrderStatus | None = None


class CancelRequest(ContractModel):
    reason: Annotated[str | None, Field(min_length=1, max_length=500)] = None


class OrderItem(ContractModel):
    product_id: UUID
    sku: str
    quantity: int
    unit_price: float
    line_total: float


class Order(ContractModel):
    id: UUID
    customer_id: UUID
    status: OrderStatus
    currency: str
    total_amount: Annotated[str, Field(pattern=r"^\d+\.\d{2}$")]
    shipping_address: Address
    items: tuple[OrderItem, ...]
    created_at: datetime
    updated_at: datetime
    version: Annotated[int, Field(ge=1)]
    cancellation_reason: str | None = None


class OrderPage(ContractModel):
    items: tuple[Order, ...]
    next_page_token: None = None


class ErrorResponse(ContractModel):
    error_code: str
    message: str
    trace_id: str
    field_errors: tuple[dict[str, str], ...] = ()


class HealthResponse(ContractModel):
    status: str
    service: str
    version: str


_PRODUCT_CATALOG: Final[dict[UUID, tuple[str, float]]] = {
    WIDGET_PRODUCT_ID: ("WIDGET-001", 24.95),
    GADGET_PRODUCT_ID: ("GADGET-002", 49.90),
}


@dataclass
class MockOrderStore:
    """Process-local state reset by every application factory invocation."""

    orders: dict[UUID, Order]

    @classmethod
    def seeded(cls) -> MockOrderStore:
        confirmed = Order(
            id=SEEDED_CONFIRMED_ORDER_ID,
            customer_id=DEFAULT_CUSTOMER_ID,
            status=OrderStatus.CONFIRMED,
            currency="USD",
            total_amount="49.90",
            shipping_address=_seed_address(),
            items=(
                OrderItem(
                    product_id=GADGET_PRODUCT_ID,
                    sku="GADGET-002",
                    quantity=1,
                    unit_price=49.90,
                    line_total=49.90,
                ),
            ),
            created_at=SEEDED_TIMESTAMP,
            updated_at=SEEDED_TIMESTAMP,
            version=1,
        )
        shipped = confirmed.model_copy(
            update={
                "id": SEEDED_SHIPPED_ORDER_ID,
                "status": OrderStatus.SHIPPED,
                "version": 2,
            }
        )
        return cls(orders={confirmed.id: confirmed, shipped.id: shipped})

    def create(self, request: OrderCreate) -> Order:
        if CREATED_ORDER_ID in self.orders:
            raise ValueError("Synthetic created-order identifier is already in use")

        items = tuple(_priced_item(item) for item in request.items)
        total = sum(item.line_total for item in items)
        order = Order(
            id=CREATED_ORDER_ID,
            customer_id=request.customer_id or DEFAULT_CUSTOMER_ID,
            status=OrderStatus.PENDING_PAYMENT,
            currency=request.currency,
            total_amount=f"{total:.2f}",
            shipping_address=request.shipping_address,
            items=items,
            created_at=SEEDED_TIMESTAMP,
            updated_at=SEEDED_TIMESTAMP,
            version=1,
        )
        self.orders[order.id] = order
        return order

    def list_orders(self) -> tuple[Order, ...]:
        return tuple(
            sorted(
                self.orders.values(),
                key=lambda order: (order.created_at, str(order.id)),
                reverse=True,
            )
        )

    def get(self, order_id: UUID) -> Order | None:
        return self.orders.get(order_id)

    def patch(self, order: Order, request: OrderPatch) -> Order:
        if request.shipping_address is None and request.status is None:
            raise ValueError("At least one order field must be supplied")

        updated = order.model_copy(
            update={
                "shipping_address": request.shipping_address or order.shipping_address,
                "status": request.status or order.status,
                "updated_at": SEEDED_TIMESTAMP,
                "version": order.version + 1,
            }
        )
        self.orders[order.id] = updated
        return updated

    def cancel(self, order: Order, reason: str | None) -> Order:
        if order.status is OrderStatus.CANCELED:
            return order
        if order.status not in {
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.CONFIRMED,
        }:
            raise ValueError("Order is not eligible for cancellation")

        cancelled = order.model_copy(
            update={
                "status": OrderStatus.CANCELED,
                "cancellation_reason": reason,
                "updated_at": SEEDED_TIMESTAMP,
                "version": order.version + 1,
            }
        )
        self.orders[order.id] = cancelled
        return cancelled


def create_mock_order_app() -> FastAPI:
    """Create a standalone ASGI mock service with deterministic seeded behavior."""

    app = FastAPI(
        title="Synthetic Mock Order API",
        version=SYNTHETIC_ORDER_API_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    store = MockOrderStore.seeded()

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="synthetic-mock-order-api",
            version=SYNTHETIC_ORDER_API_VERSION,
        )

    @app.post(
        "/orders",
        response_model=Order,
        status_code=status.HTTP_201_CREATED,
        responses={400: {"model": ErrorResponse}},
    )
    def create_order(request: OrderCreate) -> Order | JSONResponse:
        try:
            return store.create(request)
        except ValueError as error:
            return _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORDER_INPUT_INVALID",
                message=str(error),
            )

    @app.get("/orders", response_model=OrderPage)
    def list_orders() -> OrderPage:
        return OrderPage(items=store.list_orders())

    @app.get(
        "/orders/{order_id}",
        response_model=Order,
        responses={
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_order(
        order_id: UUID,
        x_mock_scenario: Annotated[MockScenario, Header()] = MockScenario.CONTRACT,
    ) -> Order | JSONResponse:
        if x_mock_scenario is MockScenario.RUNTIME_FAILURE:
            return _error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="SYNTHETIC_RUNTIME_FAILURE",
                message="Controlled synthetic runtime failure",
            )

        order = store.get(order_id)
        if order is None:
            return _error(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="ORDER_NOT_FOUND",
                message="The requested order was not found.",
            )
        if x_mock_scenario is MockScenario.MISSING_VERSION:
            payload = order.model_dump(mode="json", by_alias=True)
            payload.pop("version")
            return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
        return order

    @app.patch(
        "/orders/{order_id}",
        response_model=Order,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
        },
    )
    def patch_order(order_id: UUID, request: OrderPatch) -> Order | JSONResponse:
        order = store.get(order_id)
        if order is None:
            return _error(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="ORDER_NOT_FOUND",
                message="The requested order was not found.",
            )
        try:
            return store.patch(order, request)
        except ValueError as error:
            return _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORDER_UPDATE_INVALID",
                message=str(error),
            )

    @app.post(
        "/orders/{order_id}/cancel",
        response_model=Order,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def cancel_order(
        order_id: UUID,
        request: CancelRequest | None = None,
    ) -> Order | JSONResponse:
        order = store.get(order_id)
        if order is None:
            return _error(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="ORDER_NOT_FOUND",
                message="The requested order was not found.",
            )
        try:
            return store.cancel(order, request.reason if request is not None else None)
        except ValueError as error:
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                error_code="ORDER_CANCELLATION_INELIGIBLE",
                message=str(error),
            )

    return app


def _seed_address() -> Address:
    return Address(
        line_1="1 Synthetic Way",
        city="Example City",
        country_code="US",
        postal_code="00001",
    )


def _priced_item(request: OrderItemRequest) -> OrderItem:
    try:
        sku, unit_price = _PRODUCT_CATALOG[request.product_id]
    except KeyError as error:
        raise ValueError("Unknown synthetic product") from error
    return OrderItem(
        product_id=request.product_id,
        sku=sku,
        quantity=request.quantity,
        unit_price=unit_price,
        line_total=unit_price * request.quantity,
    )


def _error(
    *,
    status_code: int,
    error_code: str,
    message: str,
) -> JSONResponse:
    payload = ErrorResponse(
        error_code=error_code,
        message=message,
        trace_id=SYNTHETIC_TRACE_ID,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", by_alias=True),
    )


app = create_mock_order_app()
