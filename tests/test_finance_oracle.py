"""Oráculo independente em centavos inteiros para o piso financeiro (sem LLM)."""
import random

from app.intelligence import analyze, item_fingerprint, validate_quote


def cents(value: str) -> int:
    integer, fraction = value.split(".")
    return int(integer) * 100 + int(fraction)


def ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def test_100_cases_match_independent_integer_cent_oracle():
    randomizer = random.Random(20261123)
    for _ in range(100):
        quantity = randomizer.randint(1, 500)
        unit_cents = randomizer.randint(1, 200000)
        freight = randomizer.randint(0, 50000)
        packaging = randomizer.randint(0, 5000)
        other = randomizer.randint(0, 20000)
        reserve = randomizer.randint(0, 20000)
        tax_bps = randomizer.randint(0, 2400)
        margin_bps = randomizer.randint(0, 4600)

        def money(number):
            return f"{number // 100}.{number % 100:02d}"

        quote = validate_quote({
            "supplier": "Fornecedor teste independente",
            "unit_cost": money(unit_cents),
            "freight": money(freight),
            "packaging": money(packaging),
            "other": money(other),
            "risk_reserve": money(reserve),
            "tax_percent": money(tax_bps),
            "target_margin": money(margin_bps),
        })
        item = {
            "descricao": "Caneta de teste", "quantidade": quantity,
            "valor_total": money(3500000),
        }
        quote["item_fingerprint"] = item_fingerprint(
            item["descricao"], item["quantidade"]
        )
        result = analyze(item, quote)
        assert result["status"] in ("potencial_financeiro", "margem_insuficiente")

        total_cents = quantity * unit_cents + freight + packaging + other + reserve
        expected_floor = ceil_div(total_cents * 10000, 10000 - tax_bps - margin_bps)
        expected_break_even = ceil_div(total_cents * 10000, 10000 - tax_bps)
        assert cents(result["total_cost"]) == total_cents
        assert cents(result["min_viable"]) == expected_floor
        assert cents(result["break_even"]) == expected_break_even
        # A menor unidade monetária abaixo do piso NÃO pode cumprir a margem.
        assert expected_floor * (10000 - tax_bps - margin_bps) >= total_cents * 10000
        assert (expected_floor - 1) * (10000 - tax_bps - margin_bps) < total_cents * 10000


def test_minimum_bid_increases_with_higher_required_margin():
    item = {"descricao": "Papel sulfite", "quantidade": 5, "valor_total": 1000}
    values = {
        "supplier": "Fornecedor teste", "unit_cost": "50.00",
        "freight": "10.00", "packaging": "0.00",
        "other": "0.00", "risk_reserve": "0.00",
        "tax_percent": "8.00", "target_margin": "10.00",
    }
    low = validate_quote(values)
    high = validate_quote({**values, "target_margin": "25.00"})
    low["item_fingerprint"] = item_fingerprint(item["descricao"], 5)
    high["item_fingerprint"] = low["item_fingerprint"]
    assert cents(analyze(item, high)["min_viable"]) > cents(analyze(item, low)["min_viable"])
