from harness.cost import calculate_cost, get_model_pricing


def test_get_model_pricing_known():
    pricing = get_model_pricing("openai:gpt-4o")
    assert pricing is not None
    assert "input_per_1m" in pricing
    assert "output_per_1m" in pricing


def test_get_model_pricing_unknown():
    assert get_model_pricing("unknown:model") is None


def test_calculate_cost_known_model():
    cost = calculate_cost(input_tokens=1_000_000, output_tokens=500_000, model="openai:gpt-4o")
    assert cost == 7.50  # 2.50 + 5.00


def test_calculate_cost_unknown_model():
    assert calculate_cost(1000, 500, "unknown:model") == 0.0


def test_calculate_cost_zero_tokens():
    assert calculate_cost(0, 0, "openai:gpt-4o") == 0.0
