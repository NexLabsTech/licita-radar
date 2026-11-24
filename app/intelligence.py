"""Categorias indicativas e matemática financeira determinística (sem LLM)."""
import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
MAX_MONEY = Decimal("100000000.00")

# Categorias são heurísticas, não uma prova de facilidade de fornecimento.
CATEGORY_RULES = (
    ("papelaria", "Papelaria e escritório", ("papel", "caneta", "caderno", "lapis", "borracha", "envelope", "grampeador", "toner", "pasta arquivo", "resma")),
    ("limpeza", "Limpeza e higiene", ("detergente", "desinfetante", "sabao", "alcool gel", "vassoura", "rodo", "papel higienico", "saco de lixo", "esponja", "limpeza")),
    ("mercado", "Mercado e mercearia", ("acucar", "cafe", "arroz", "feijao", "oleo vegetal", "biscoito", "leite em po", "sal refinado", "macarrao")),
    ("copa", "Copa e cozinha", ("copo", "prato", "talher", "garrafa termica", "panela", "guardanapo", "utensilio", "cozinha")),
    ("epi", "EPI e segurança", ("capacete", "luva de seguranca", "oculos de protecao", "protetor auricular", "respirador", "bota de seguranca", "epi")),
    ("moveis", "Móveis simples", ("cadeira", "mesa", "armario", "estante", "gaveteiro", "mobiliario")),
    ("eletrica", "Elétrica leve", ("lampada", "extensao eletrica", "tomada", "interruptor", "fio eletrico", "cabo flexivel")),
    ("hidraulica", "Hidráulica leve", ("tubo pvc", "joelho pvc", "registro de agua", "torneira", "conexao hidraulica")),
    ("ferragens", "Ferragens leves", ("parafuso", "porca sextavada", "arruela", "dobradica", "cadeado", "ferragem")),
    ("informatica", "Informática básica", ("mouse", "teclado", "pendrive", "monitor", "webcam", "roteador", "computador")),
)
CATEGORIES = {"outros": "Outros / a verificar", **{key: label for key, label, _ in CATEGORY_RULES}}
SIMPLE_CATEGORIES = frozenset({"papelaria", "limpeza", "mercado", "copa"})


def normalized(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join("".join(char for char in raw if not unicodedata.combining(char)).split())


def classify(description: str) -> str:
    text = " " + normalized(description) + " "
    for category, _, terms in CATEGORY_RULES:
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms):
            return category
    return "outros"


def item_fingerprint(description: str, quantity: object) -> str:
    try:
        qty = Decimal(str(quantity)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        qty = Decimal(0)
    value = normalized(description) + "\n" + str(qty)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decimal_field(value: object, field: str, maximum: Decimal = MAX_MONEY,
                  positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field}: informe um número válido.") from exc
    if not parsed.is_finite() or parsed > maximum or parsed < 0 or (positive and parsed == 0):
        raise ValueError(f"{field}: valor fora dos limites permitidos.")
    if parsed != parsed.quantize(CENT):
        raise ValueError(f"{field}: use no máximo duas casas decimais.")
    return parsed.quantize(CENT)


def validate_quote(data: dict) -> dict[str, str]:
    supplier = str(data.get("supplier") or "").strip()
    if not 2 <= len(supplier) <= 120:
        raise ValueError("Fornecedor: informe de 2 a 120 caracteres.")
    fields = ("unit_cost", "freight", "packaging", "other", "risk_reserve",
              "tax_percent", "target_margin")
    amounts = {}
    for key in fields:
        maximum = Decimal("99.99") if key in ("tax_percent", "target_margin") else MAX_MONEY
        amounts[key] = decimal_field(
            data.get(key), key, maximum=maximum, positive=(key == "unit_cost")
        )
    if amounts["tax_percent"] >= Decimal("100") or amounts["target_margin"] >= Decimal("100"):
        raise ValueError("As taxas devem ser menores que 100%.")
    if amounts["tax_percent"] + amounts["target_margin"] >= HUNDRED:
        raise ValueError("Soma dos tributos e margem desejada precisa ser menor que 100%.")
    return {"supplier": supplier, **{key: str(amounts[key]) for key in fields}}


def analyze(item: dict, quote: dict | None) -> dict:
    category = classify(str(item.get("descricao") or ""))
    result = {
        "category": category, "category_label": CATEGORIES[category],
        "ease": "Compra comum (indicativo)" if category in SIMPLE_CATEGORIES else "Verificar especificações",
        "status": "sem_cotacao",
        "note": "Cadastre uma cotação real para calcular preços. Categoria apenas indicativa.",
        "break_even": None, "min_viable": None, "profit_reference": None,
        "margin_reference": None, "surplus": None, "total_cost": None,
        "reference": None, "quantity": item.get("quantidade"), "supplier": None,
    }
    if quote is None:
        return result
    if quote.get("item_fingerprint") != item_fingerprint(
        str(item.get("descricao") or ""), item.get("quantidade")
    ):
        result["status"] = "desatualizada"
        result["note"] = "Descrição ou quantidade mudou no PNCP. Revise e salve uma nova cotação."
        return result

    try:
        qty = Decimal(str(item.get("quantidade")))
        if not qty.is_finite() or qty <= 0 or qty > Decimal("100000000"):
            raise InvalidOperation()
        unit = Decimal(str(quote["unit_cost"]))
        freight = Decimal(str(quote["freight"]))
        packaging = Decimal(str(quote["packaging"]))
        other = Decimal(str(quote["other"]))
        reserve = Decimal(str(quote["risk_reserve"]))
        tax = Decimal(str(quote["tax_percent"])) / HUNDRED
        margin = Decimal(str(quote["target_margin"])) / HUNDRED
        if not all(v.is_finite() for v in (unit, freight, packaging, other, reserve, tax, margin)):
            raise InvalidOperation()
        if unit <= 0 or min(freight, packaging, other, reserve, tax, margin) < 0:
            raise InvalidOperation()
        if tax + margin >= 1:
            raise InvalidOperation()
    except (InvalidOperation, TypeError, ValueError, KeyError):
        result["status"] = "invalida"
        result["note"] = "Dados financeiros ou quantidade inválidos; revise a cotação."
        return result

    cost = (unit * qty + freight + packaging + other + reserve).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    break_even = (cost / (1 - tax)).quantize(CENT, rounding=ROUND_CEILING)
    minimum = (cost / (1 - tax - margin)).quantize(CENT, rounding=ROUND_CEILING)
    result.update({
        "total_cost": str(cost), "break_even": str(break_even),
        "min_viable": str(minimum), "supplier": quote["supplier"],
    })

    reference_raw = item.get("valor_total")
    try:
        reference = Decimal(str(reference_raw))
        if not reference.is_finite() or reference <= 0:
            raise InvalidOperation()
    except (InvalidOperation, TypeError, ValueError):
        result["status"] = "sem_referencia"
        result["note"] = (
            "Piso calculado com seus custos; sem preço oficial disponível para comparar."
        )
        return result
    reference = reference.quantize(CENT, rounding=ROUND_HALF_UP)
    profit = (reference * (1 - tax) - cost).quantize(CENT, rounding=ROUND_HALF_UP)
    realized_margin = ((profit / reference) * HUNDRED).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    surplus = (reference - minimum).quantize(CENT, rounding=ROUND_HALF_UP)
    result.update({
        "reference": str(reference), "profit_reference": str(profit),
        "margin_reference": str(realized_margin), "surplus": str(surplus),
    })
    if reference < minimum:
        result["status"] = "margem_insuficiente"
        result["note"] = (
            "Preço de referência abaixo do piso para sua margem; revisar custos ou descartar."
        )
    else:
        result["status"] = "potencial_financeiro"
        result["note"] = (
            "O valor de referência comporta sua margem informada, mas não garante "
            "disputa aberta, preço vencedor ou lucro. Confira edital, estoque e prazo."
        )
    return result
