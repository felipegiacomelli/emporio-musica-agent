"""Policy rules as code: purchase quotes (§3, §5, §6.2) and returns (§4, §8).

The model never does this arithmetic or rule evaluation; it calls these
through tools and reports the result.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from emporio.data import Store, fold, money

PIX_FACTOR = Decimal("0.95")
# §3.1: (max installments in the tier, minimum installment value)
INSTALLMENT_TIERS = [(3, Decimal(50)), (6, Decimal(80)), (12, Decimal(100))]
# §5.1: assumption — the metropolitan region is the city of Campo Grande.
METRO_CITIES = {"campo grande"}
FREE_SHIPPING_ABOVE = Decimal(500)
METRO_FEE = Decimal(35)
SPLIT_PAYMENT_ABOVE = Decimal(2000)
CONTACT = (
    "Para iniciar, fale com a equipe pelo WhatsApp (67) 3341-4444 ou pelo "
    "e-mail contato@emporiodamusica.com.br."
)
UNAVAILABLE_REASON = {"discontinued": "descontinuado", "coming_soon": "em breve"}


def unavailable_reason(status: str, stock: int) -> str | None:
    if status != "active":
        return UNAVAILABLE_REASON.get(status, status)
    return "sem estoque" if stock <= 0 else None


def _min_installment(n: int) -> Decimal:
    return next(v for limit, v in INSTALLMENT_TIERS if n <= limit)


# --- quote_purchase -----------------------------------------------------------


class QuoteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    quantity: int = Field(ge=1, le=20)


class QuoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[QuoteItem] = Field(min_length=1)
    installments: int | None = Field(None, ge=1, le=12)
    delivery_city: str | None = None


def _shipping(city: str | None, subtotal: Decimal) -> dict[str, Any]:
    if not city:
        return {"fee": None, "note": "Informe a cidade de entrega para o frete."}
    if fold(city) in METRO_CITIES:
        fee = Decimal(0) if subtotal > FREE_SHIPPING_ABOVE else METRO_FEE
        return {
            "fee": str(money(fee)),
            "deadline": "1 a 3 dias úteis (motoboy)",
            "rule": "§5.1: grátis acima de R$ 500,00; abaixo, R$ 35,00",
        }
    return {
        "fee": None,
        "note": (
            "Fora da região de Campo Grande o frete é calculado pelo CEP no "
            "fechamento do pedido (PAC 5 a 12, SEDEX 2 a 5, Jadlog 3 a 8 dias "
            "úteis). Instrumentos de grande porte podem exigir cotação especial."
        ),
    }


def quote_purchase(store: Store, args: QuoteArgs) -> dict[str, Any]:
    lines, problems = [], []
    subtotal = pix_total = Decimal(0)
    for item in args.items:
        product = store.product(item.product_id)
        if product is None:
            problems.append(f"produto {item.product_id} não existe")
            continue
        reason = unavailable_reason(product.status, product.stock)
        if reason or item.quantity > product.stock:
            problems.append(
                f"{product.name} indisponível ({reason or 'estoque insuficiente'})"
            )
            continue
        unit_pix = (
            product.final_price
            if product.promotion
            else money(product.price * PIX_FACTOR)
        )
        line_total = product.final_price * item.quantity
        subtotal += line_total
        pix_total += unit_pix * item.quantity
        lines.append(
            {
                "product_id": product.id,
                "name": product.name,
                "quantity": item.quantity,
                "unit_price": str(money(product.price)),
                "promotion_percent": (
                    product.promotion.percent if product.promotion else None
                ),
                "unit_final_price": str(product.final_price),
                "unit_pix_price": str(unit_pix),
                "line_total": str(money(line_total)),
            }
        )
    if problems:
        return {"error": "; ".join(problems)}

    options = [
        {"n": n, "value": str(money(subtotal / n))}
        for n in range(1, 13)
        if money(subtotal / n) >= _min_installment(n)
    ]
    requested = None
    if args.installments:
        n = args.installments
        requested = {
            "n": n,
            "value": str(money(subtotal / n)),
            "allowed": money(subtotal / n) >= _min_installment(n),
            "minimum": str(money(_min_installment(n))),
        }
    shipping = _shipping(args.delivery_city, subtotal)
    fee = Decimal(shipping["fee"]) if shipping["fee"] is not None else None
    return {
        "lines": lines,
        "subtotal": str(money(subtotal)),
        "pix_total": str(money(pix_total)),
        "pix_rule": "§6.2: 5% no PIX só em itens sem promoção",
        "installment_options": options,
        "max_installments": options[-1] if options else None,
        "requested_installments": requested,
        "shipping": shipping,
        "total": str(money(subtotal + fee)) if fee is not None else None,
        "pix_total_with_shipping": (
            str(money(pix_total + fee)) if fee is not None else None
        ),
        "split_payment_allowed": subtotal > SPLIT_PAYMENT_ABOVE,
    }


# --- check_return -------------------------------------------------------------


class ReturnArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["arrependimento", "defeito", "preferencia"]
    channel: Literal["online", "loja"] | None = None
    received_on: date | None = None
    days_since_receipt: int | None = Field(None, ge=0)
    purchased_on: date | None = None
    days_since_purchase: int | None = Field(None, ge=0)
    used: bool | None = None
    original_packaging: bool | None = None
    customized: bool | None = None
    final_sale: bool | None = None


def _days(on: date | None, days: int | None, today: date) -> int | None:
    if on is None:
        return days
    if on > today:
        raise ValueError(f"data no futuro: {on.isoformat()}")
    return (today - on).days


def check_return(args: ReturnArgs, today: date) -> dict[str, Any]:
    receipt = _days(args.received_on, args.days_since_receipt, today)
    purchase = _days(args.purchased_on, args.days_since_purchase, today)
    reasons: list[str] = []
    missing: list[str] = []
    conditions: list[str] = []
    alternative = None

    if args.reason == "arrependimento":
        rule = "§4.1"
        if args.channel == "loja":
            reasons.append("o direito de arrependimento vale só para compras online")
            alternative = "Troca por preferência em até 7 dias (§4.3)."
        elif args.channel is None:
            missing.append("a compra foi online ou na loja?")
        if receipt is None:
            missing.append("quando o produto foi recebido?")
        elif receipt > 7:
            reasons.append(
                f"recebido há {receipt} dias; o prazo é de 7 dias corridos após o"
                " recebimento"
            )
        if args.used is None:
            missing.append("o produto foi usado?")
        elif args.used:
            reasons.append("o produto não pode ter sinais de uso")
        if args.original_packaging is None:
            missing.append("está na embalagem original, com acessórios e manuais?")
        elif not args.original_packaging:
            reasons.append("o produto precisa estar na embalagem original")
        conditions = [
            "Reembolso na mesma forma de pagamento em até 10 dias úteis.",
            "Frete de devolução por conta da loja.",
        ]
    elif args.reason == "defeito":
        rule = "§4.2"
        if purchase is None:
            missing.append("qual a data da compra?")
        elif purchase > 30:
            reasons.append(
                f"compra há {purchase} dias; a troca por defeito na loja vale até 30"
                " dias após a compra"
            )
            alternative = (
                "Acionar a garantia do fabricante (6 meses a 2 anos, §8.2); a loja"
                " pode intermediar. A garantia legal é de 90 dias após o"
                " recebimento (§8.1)."
            )
        conditions = [
            "Sujeito a análise: mau uso, quedas, umidade excessiva e modificações"
            " não autorizadas não são cobertos."
        ]
    else:
        rule = "§4.3"
        if receipt is None:
            missing.append("quando o produto foi recebido?")
        elif receipt > 7:
            reasons.append(f"recebido há {receipt} dias; o prazo é de 7 dias")
        if args.used is None:
            missing.append("o produto foi usado?")
        elif args.used:
            reasons.append("o produto precisa estar em perfeito estado")
        if args.original_packaging is None:
            missing.append("está na embalagem original?")
        elif not args.original_packaging:
            reasons.append("o produto precisa estar na embalagem original")
        if args.customized:
            reasons.append("instrumentos personalizados não são trocados (§4.4)")
        if args.final_sale:
            reasons.append("itens de liquidação 'venda final' não são trocados (§4.4)")
        conditions = [
            "Mediante disponibilidade do produto desejado; diferenças de valor são"
            " cobradas ou reembolsadas."
        ]

    decision = (
        "fora_da_politica"
        if reasons
        else "faltam_dados" if missing else "pode_solicitar"
    )
    return {
        "decision": decision,
        "rule": rule,
        "days_since_receipt": receipt,
        "days_since_purchase": purchase,
        "reasons": reasons,
        "missing": missing,
        "conditions": conditions,
        "alternative": alternative,
        "next_step": CONTACT,
        "note": "Esta é uma verificação das regras; quem aprova é a equipe.",
    }
