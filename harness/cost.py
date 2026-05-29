"""Cost calculation from token usage and model pricing."""

# Pricing per 1M tokens (USD). Update as providers change pricing.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "openai:gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "openai:gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "openai:gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "openai:gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "openai:gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "anthropic:claude-sonnet-4-6": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "anthropic:claude-sonnet-4-7": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "anthropic:claude-opus-4-7": {"input_per_1m": 15.00, "output_per_1m": 75.00},
    "anthropic:claude-haiku-4-5": {"input_per_1m": 0.80, "output_per_1m": 4.00},
    "deepseek:deepseek-chat": {"input_per_1m": 0.27, "output_per_1m": 1.10},
    "google:gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "google:gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
}


def get_model_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a model. Returns None if unknown."""
    return _MODEL_PRICING.get(model)


def calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Calculate USD cost for token usage on a given model."""
    pricing = get_model_pricing(model)
    if not pricing:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return round(input_cost + output_cost, 6)
