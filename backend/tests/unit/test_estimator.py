from decimal import Decimal

from cardfactory.finance.estimator import estimate_call

PRICING = {"prompt": "0.000001", "completion": "0.000004", "request": "0"}


def test_estimate_includes_output_ceiling_and_repair():
    e = estimate_call(PRICING, input_chars=2500, max_output_tokens=1000, repair_attempts=1)
    assert e.safe
    one = Decimal("0.000001") * e.basis["tokens_in_upper"] + Decimal("0.000004") * 1000
    assert e.max_usd == one * 2


def test_unestimable_blocks():
    assert not estimate_call(None, input_chars=10, max_output_tokens=10).safe
    assert not estimate_call({"prompt": "1"}, input_chars=10, max_output_tokens=10).safe
    e = estimate_call(PRICING, input_chars=10, max_output_tokens=10, web_searches=2)
    assert not e.safe and "pesquisa" in e.reasons[0]


def test_negative_price_is_unsafe():
    assert not estimate_call({"prompt": "-1", "completion": "-1"}, input_chars=1, max_output_tokens=1).safe


def test_reasoning_price_used_when_higher():
    p = dict(PRICING, internal_reasoning="0.00001")
    e = estimate_call(p, input_chars=0, max_output_tokens=100, repair_attempts=0)
    assert e.basis["price_out"] == "0.00001"


def test_web_search_price_as_text_from_scope():
    e = estimate_call(PRICING, input_chars=10, max_output_tokens=10, web_searches=2, web_search_price_usd="0.02")
    assert e.safe and e.max_usd > 0
