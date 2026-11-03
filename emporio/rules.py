"""Policy rules as code: purchase quotes (§3, §5, §6.2) and returns (§4, §8).

The model never does this arithmetic or rule evaluation; it calls these
through tools and reports the result.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from emporio.clean import INSTALLMENT_TIERS
from emporio.data import Store, brl, fold, money

PIX_FACTOR = Decimal("0.95")
# §5.1: assumption — the metropolitan region is the city of Campo Grande.
METRO_CITIES = {"campo grande"}
FREE_SHIPPING_ABOVE = Decimal(500)
METRO_FEE = Decimal(35)
SPLIT_PAYMENT_ABOVE = Decimal(2000)
CONTACT = (
    "Para iniciar, fale com a equipe pelo WhatsApp (67) 3341-4444 ou pelo "
    "e-mail contato@emporiodamusica.com.br."
)
RULE_SUMMARY = {
    "arrependimento": (
        "Compras online: devolução em até 7 dias corridos após o recebimento, "
        "sem justificativa. O produto deve estar sem sinais de uso, na "
        "embalagem original, com acessórios e manuais. Reembolso na mesma forma "
        "de pagamento em até 10 dias úteis; frete de devolução por conta da "
        "loja (§4.1)."
    ),
    "defeito": (
        "Defeito de fabricação: troca em até 30 dias corridos após a compra. "
        "Depois disso, vale a garantia do fabricante, e a loja pode "
        "intermediar. Mau uso, quedas, umidade e modificações não são cobertos "
        "(§4.2, §8)."
    ),
    "preferencia": (
        "Troca por preferência (cor, modelo, tamanho) em até 7 dias, mediante "
        "disponibilidade, com o produto em perfeito estado e na embalagem "
        "original; diferenças de valor são cobradas ou reembolsadas. Não vale "
        "para instrumentos personalizados nem itens de liquidação 'venda "
        "final' (§4.3, §4.4)."
    ),
}
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


def _shipping_fee(city: str | None, subtotal: Decimal) -> Decimal | None:
    if city and fold(city) in METRO_CITIES:
        return Decimal(0) if subtotal > FREE_SHIPPING_ABOVE else METRO_FEE
    return None


def _shipping(city: str | None, fee: Decimal | None) -> dict[str, Any]:
    if not city:
        return {"fee": None, "note": "Informe a cidade de entrega para o frete."}
    if fee is not None:
        return {
            "fee": brl(fee),
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
    quantities: dict[int, int] = {}  # same product twice -> one line
    for item in args.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
    for product_id, quantity in quantities.items():
        product = store.product(product_id)
        if product is None:
            problems.append(f"produto {product_id} não existe")
            continue
        reason = unavailable_reason(product.status, product.stock)
        if reason or quantity > product.stock:
            problems.append(
                f"{product.name} indisponível ({reason or 'estoque insuficiente'})"
            )
            continue
        unit_pix = (
            product.final_price
            if product.promotion
            else money(product.price * PIX_FACTOR)
        )
        line_total = product.final_price * quantity
        subtotal += line_total
        pix_total += unit_pix * quantity
        lines.append(
            {
                "product_id": product.id,
                "name": product.name,
                "quantity": quantity,
                "unit_price": brl(product.price),
                "promotion_percent": (
                    product.promotion.percent if product.promotion else None
                ),
                "unit_final_price": brl(product.final_price),
                "unit_pix_price": brl(unit_pix),
                "line_total": brl(line_total),
            }
        )
    if problems:
        return {"error": "; ".join(problems)}

    options = [
        {"n": n, "value": brl(subtotal / n)}
        for n in range(1, 13)
        if money(subtotal / n) >= _min_installment(n)
    ]
    requested = None
    if args.installments:
        n = args.installments
        requested = {
            "n": n,
            "value": brl(subtotal / n),
            "allowed": money(subtotal / n) >= _min_installment(n),
            "minimum": brl(_min_installment(n)),
        }
    fee = _shipping_fee(args.delivery_city, subtotal)
    shipping = _shipping(args.delivery_city, fee)
    return {
        "lines": lines,
        "subtotal": brl(subtotal),
        "pix_total": brl(pix_total),
        "pix_rule": "§6.2: 5% no PIX só em itens sem promoção",
        "installment_options": options,
        "max_installments": options[-1] if options else None,
        "requested_installments": requested,
        "shipping": shipping,
        "total": brl(subtotal + fee) if fee is not None else None,
        "pix_total_with_shipping": (brl(pix_total + fee) if fee is not None else None),
        "split_payment_allowed": subtotal > SPLIT_PAYMENT_ABOVE,
    }


# --- check_return -------------------------------------------------------------


class ReturnArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["arrependimento", "defeito", "preferencia"]
    channel: Literal["online", "loja"] | None = None
    received_on: str | None = None  # as the customer said it: dd/mm[/aaaa]
    days_since_receipt: int | None = Field(None, ge=0)
    purchased_on: str | None = None
    days_since_purchase: int | None = Field(None, ge=0)
    used: bool | None = None
    original_packaging: bool | None = None
    customized: bool | None = None
    final_sale: bool | None = None


def customer_date(text: str, today: date) -> date:
    """Parse "25/10", "25/10/2026" or "2026-10-25"; a date without a year is
    the most recent one that is not in the future."""
    text = text.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", text)
    if not m:
        raise ValueError(f"data inválida: {text!r}; use dd/mm ou dd/mm/aaaa")
    day, month = int(m.group(1)), int(m.group(2))
    if m.group(3):
        year = int(m.group(3))
        return date(year + 2000 if year < 100 else year, month, day)
    parsed = date(today.year, month, day)
    return parsed if parsed <= today else date(today.year - 1, month, day)


def _days(text: str | None, days: int | None, today: date) -> int | None:
    if text is None:
        return days
    on = customer_date(text, today)
    if on > today:
        raise ValueError(f"data no futuro: {on.strftime('%d/%m/%Y')}")
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
        "rule_summary": RULE_SUMMARY[args.reason],
        "days_since_receipt": receipt,
        "days_since_purchase": purchase,
        "reasons": reasons,
        "missing": missing,
        "conditions": conditions,
        "alternative": alternative,
        "next_step": CONTACT,
        "note": "Esta é uma verificação das regras; quem aprova é a equipe.",
    }
