"""LLM client — manages httpx, OpenAI provider, model, and agent creation.

All settings read from env vars with explicit-arg overrides.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


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
        self._model = OpenAIChatModel(
            model_name=self._model_name,
            provider=self._provider,
        )

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
        stream_callback: Any | None = None,
    ) -> PydanticAgent:
        """Create a configured PydanticAgent from this client."""
        agent = PydanticAgent(
            model=self._model,
            system_prompt=system_prompt,
            retries=retries,
            output_type=output_type,
            defer_model_check=True,
            tools=tools or [],
            deps_type=deps_type,
        )
        if stream_callback:
            agent._stream_callback = stream_callback
        return agent
