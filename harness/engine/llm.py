"""LLM client — manages httpx, OpenAI provider, model, and agent creation.

All settings read from env vars with explicit-arg overrides.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import httpx
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings


def _is_deepseek(model_name: str, api_url: str) -> bool:
    """Heuristic: model name starts with 'deepseek' or URL contains 'deepseek'."""
    mn = model_name.lower()
    if mn.startswith("deepseek"):
        return True
    if "deepseek" in api_url.lower():
        return True
    return False


def _is_thinking_model(model_name: str) -> bool:
    """Check if the model is known to support thinking/reasoning."""
    mn = model_name.lower()
    return any(kw in mn for kw in ("reasoner", "reasoning", "r1", "think"))


def _should_enable_thinking(model_name: str) -> bool:
    """Decide whether to enable thinking based on env config and model name.

    HARNESS_THINKING values:
      - "true":  always enable
      - "false": always disable
      - "auto":  enable if model name looks like a thinking model (default)
    """
    setting = os.environ.get("HARNESS_THINKING", "auto").lower()
    if setting == "true":
        return True
    if setting == "false":
        return False
    # auto: detect from model name
    return _is_thinking_model(model_name)


class LLMClient:
    """Manages httpx client, OpenAI provider, model, and agent creation.

    Usage:
        client = LLMClient()
        agent = client.agent(system_prompt="You are helpful.", output_type=str)
        result = agent.run_sync("hi")

    Or override env vars:
        client = LLMClient(model="gpt-4o", proxy="http://127.0.0.1:7890", ssl_verify=False)
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        proxy: str | None = None,
        ssl_verify: bool | None = None,
    ):
        self._model_name = model or os.environ.get("HARNESS_MODEL", "")
        if not self._model_name:
            raise RuntimeError(
                "No model configured. Set HARNESS_MODEL env var (e.g. 'gpt-4o')."
            )

        self._api_key = api_key or os.environ.get("HARNESS_API_KEY", "")
        self._api_url = api_url or os.environ.get("HARNESS_API_URL", "")
        self._proxy = proxy or os.environ.get("HARNESS_PROXY", "")
        self._ssl_verify = (
            ssl_verify
            if ssl_verify is not None
            else os.environ.get("HARNESS_SSL_VERIFY", "true").lower() != "false"
        )

        # Build httpx client
        client_kwargs: dict[str, Any] = {"verify": self._ssl_verify}
        if self._proxy:
            client_kwargs["proxy"] = self._proxy
        self._http_client = httpx.AsyncClient(**client_kwargs)

        # Build provider + model
        provider_kwargs: dict[str, Any] = {
            "http_client": self._http_client,
        }
        if self._api_key:
            provider_kwargs["api_key"] = self._api_key
        if self._api_url:
            provider_kwargs["base_url"] = self._api_url

        self._provider = OpenAIProvider(**provider_kwargs)

        # DeepSeek V4 / reasoner don't support tool_choice=required.
        # OpenAIProvider doesn't know this, so override the profile.
        model_kwargs: dict[str, Any] = {
            "model_name": self._model_name,
            "provider": self._provider,
        }
        if _is_deepseek(self._model_name, self._api_url):
            base_profile = self._provider.model_profile(self._model_name)
            if base_profile and getattr(base_profile, "openai_supports_tool_choice_required", True):
                model_kwargs["profile"] = dataclasses.replace(
                    base_profile, openai_supports_tool_choice_required=False
                )

        self._model = OpenAIChatModel(**model_kwargs)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def api_url(self) -> str:
        return self._api_url

    def agent(
        self,
        system_prompt: str,
        output_type: type = str,
        retries: int = 3,
        tools: list | None = None,
        deps_type: type | None = None,
    ) -> PydanticAgent:
        """Create a configured PydanticAgent from this client."""
        model_settings = None
        if _should_enable_thinking(self._model_name):
            model_settings = ModelSettings(thinking=True)

        return PydanticAgent(
            model=self._model,
            system_prompt=system_prompt,
            retries=retries,
            output_type=output_type,
            defer_model_check=True,
            tools=tools or [],
            deps_type=deps_type,
            model_settings=model_settings,
        )
