"""The agent's two tools: pure functions over the loaded store.

Rules enforced here, not in the prompt:
- availability (active and in stock) and promotion math;
- order details only for a matching order number + e-mail/phone pair.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from emporio.data import Order, Product, Store, digits, fold, money

MAX_RESULTS = 10
NOT_FOUND = (
    "Não encontrei um pedido com esses dados. Confira o número do pedido e o "
    "e-mail ou telefone usados na compra."
)
STATUS_PT = {
    "pending": "pendente",
    "confirmed": "confirmado",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
OPEN_STATUSES = {"pending", "confirmed", "shipped"}

# Everyday words for each category, so "violão yamaha" in `query` still hits
# the "Violões" category (the model puts the instrument word in the query).
CATEGORY_ALIASES = {
    "Guitarras": "guitarra",
    "Baixos": "baixo contrabaixo",
    "Baterias e Percussão": "bateria percussao",
    "Teclados e Pianos": "teclado piano sintetizador",
    "Violões": "violao",
    "Instrumentos de Sopro (Madeiras)": "flauta clarinete saxofone sax oboe",
    "Instrumentos de Sopro (Metais)": "trompete trombone tuba trompa",
    "Cordas Orquestrais": "violino viola violoncelo",
    "Ukuleles": "ukulele",
}


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    category: str | None = None
    max_price: Decimal | None = Field(None, gt=0)
    on_promotion: bool = False
    include_unavailable: bool = False

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str | None) -> str | None:
        if value is not None and value not in CATEGORY_ALIASES:
            raise ValueError(f"categoria inválida; use: {list(CATEGORY_ALIASES)}")
        return value


class OrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int
    email_or_phone: str = Field(min_length=3)


def _haystacks(product: Product) -> tuple[str, str]:
    text = fold(
        " ".join(
            [
                product.name,
                product.category.name,
                CATEGORY_ALIASES.get(product.category.name, ""),
                *product.specs.values(),
            ]
        )
    )
    return text, text.replace(" ", "")


def _matches(product: Product, query: str) -> bool:
    spaced, compact = _haystacks(product)
    return all(tok in spaced or tok in compact for tok in fold(query).split())


def _render_product(p: Product) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category.name,
        "price": str(money(p.price)),
        "final_price": str(p.final_price),
        "promotion": (
            None
            if p.promotion is None
            else {"percent": p.promotion.percent, "name": p.promotion.name}
        ),
        "stock": p.stock,
        "status": p.status,
        "available": p.available,
        "specs": p.specs,
        "description": p.description,
    }


def search_products(store: Store, args: SearchArgs) -> dict[str, Any]:
    found = [
        p
        for p in store.products
        if (args.include_unavailable or p.available)
        and (args.category is None or p.category.name == args.category)
        and (args.max_price is None or p.final_price <= args.max_price)
        and (not args.on_promotion or p.promotion is not None)
        and (not args.query or _matches(p, args.query))
    ]
    found.sort(key=lambda p: (p.final_price, p.id))
    return {
        "results": [_render_product(p) for p in found[:MAX_RESULTS]],
        "more": max(0, len(found) - MAX_RESULTS),
    }


def _contact_matches(order: Order, contact: str) -> bool:
    contact = contact.strip()
    if "@" in contact:
        return contact.casefold() == order.customer.email.casefold()
    phone = digits(contact)
    return bool(phone) and phone == digits(order.customer.phone)


def get_order(store: Store, args: OrderArgs, today: date) -> dict[str, Any]:
    order = store.orders.get(args.order_id)
    if order is None or not _contact_matches(order, args.email_or_phone):
        return {"error": NOT_FOUND}
    eta = order.estimated_delivery
    return {
        "order_id": order.id,
        "customer_first_name": order.customer.name.split()[0],
        "status": order.status,
        "status_pt": STATUS_PT.get(order.status, order.status),
        "order_date": order.order_date.isoformat(),
        "items": [
            {"name": i.product_name, "quantity": i.quantity} for i in order.items
        ],
        "total": str(money(order.total)),
        "payment_method": order.payment_method,
        "tracking_code": order.tracking_code,
        "estimated_delivery": eta.isoformat() if eta else None,
        "delivery_overdue": (
            order.status in OPEN_STATUSES and eta is not None and eta < today
        ),
        "notes": order.notes,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {**schema, "type": [schema["type"], "null"]}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_products",
        "description": (
            "Busca produtos no catálogo da loja, com preço, promoção ativa e "
            "estoque atuais. Use `category` para o tipo de instrumento e "
            "`query` para marca/modelo. Por padrão só retorna produtos "
            "disponíveis; use include_unavailable=true para explicar por que "
            "um produto citado pelo cliente não está disponível."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": _nullable(
                    {"type": "string", "description": "Marca, modelo ou palavras."}
                ),
                "category": {
                    "type": ["string", "null"],
                    "enum": [*CATEGORY_ALIASES, None],
                },
                "max_price": _nullable(
                    {
                        "type": "number",
                        "description": "Preço máximo em R$ (preço final).",
                    }
                ),
                "on_promotion": {
                    "type": "boolean",
                    "description": "Só produtos com promoção ativa.",
                },
                "include_unavailable": {"type": "boolean"},
            },
            "required": [
                "query",
                "category",
                "max_price",
                "on_promotion",
                "include_unavailable",
            ],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_order",
        "description": (
            "Consulta um pedido. Exige o número do pedido E o e-mail ou "
            "telefone usado na compra; peça os dois ao cliente antes de chamar."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "email_or_phone": {"type": "string"},
            },
            "required": ["order_id", "email_or_phone"],
            "additionalProperties": False,
        },
    },
]


def run_tool(store: Store, name: str, arguments: str, today: date) -> str:
    """Run one tool call. Never raises: bad input becomes an error the model sees."""
    try:
        raw = json.loads(arguments)
        if not isinstance(raw, dict):
            raise ValueError("argumentos devem ser um objeto JSON")
        if name == "search_products":
            result = search_products(store, SearchArgs.model_validate(raw))
        elif name == "get_order":
            result = get_order(store, OrderArgs.model_validate(raw), today)
        else:
            result = {"error": f"ferramenta desconhecida: {name}"}
    except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
        result = {"error": f"argumentos inválidos: {exc}"}
    return json.dumps(result, ensure_ascii=False)
