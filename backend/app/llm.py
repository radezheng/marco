from __future__ import annotations

from collections.abc import Iterable

from openai import AzureOpenAI, OpenAI

from .config import settings


def _is_openai_compatible_endpoint(endpoint: str) -> bool:
    # Azure AI Foundry / Azure OpenAI can expose an OpenAI-compatible endpoint
    # such as: https://{resource}.openai.azure.com/openai/v1/
    return "/openai/v1" in endpoint


def _normalize_base_url(endpoint: str) -> str:
    # OpenAI SDK expects base_url without query params; ensure trailing slash.
    return endpoint.rstrip("/") + "/"


def azure_client() -> AzureOpenAI | OpenAI | None:
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        return None

    endpoint = settings.azure_openai_endpoint.strip()
    if _is_openai_compatible_endpoint(endpoint):
        # OpenAI-compatible endpoint: model == deployment name
        return OpenAI(
            base_url=_normalize_base_url(endpoint),
            api_key=settings.azure_openai_api_key,
        )

    # Classic Azure OpenAI endpoint: uses api-version query and /openai/deployments/{deployment}
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def explain_snapshot(prompt: str) -> str:
    client = azure_client()
    if client is None:
        raise RuntimeError("Azure OpenAI not configured")

    resp = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": "你是严谨的宏观监控助手。只基于给定数据解释，不要编造数据。"},
            {"role": "user", "content": prompt},
        ],
        temperature=1,
    )
    return resp.choices[0].message.content or ""


def _chunk_delta_text(chunk) -> str:
    """Extract delta text from a streamed chat.completions chunk."""
    try:
        choice0 = chunk.choices[0]
        delta = getattr(choice0, "delta", None)
        if delta is None:
            return ""
        content = getattr(delta, "content", None)
        return content or ""
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""


def explain_snapshot_stream(prompt: str) -> Iterable[str]:
    client = azure_client()
    if client is None:
        raise RuntimeError("Azure OpenAI not configured")

    stream = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": "你是严谨的宏观监控助手。只基于给定数据解释，不要编造数据。"},
            {"role": "user", "content": prompt},
        ],
        temperature=1,
        stream=True,
    )

    for chunk in stream:
        delta = _chunk_delta_text(chunk)
        if delta:
            yield delta
