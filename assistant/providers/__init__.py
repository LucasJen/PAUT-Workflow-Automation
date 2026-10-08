"""The language model providers the assistant can use, by key (Preferences › Assistant lists them)."""
from .anthropic_provider import AnthropicProvider
from .base import ModelInfo, Provider, ProviderError, Reply, TextDelta, ToolCall, Usage  # noqa: F401

PROVIDERS = {p.key: p for p in (AnthropicProvider(),)}
DEFAULT_PROVIDER = 'anthropic'


def get_provider(key):
    return PROVIDERS.get(key) or PROVIDERS[DEFAULT_PROVIDER]


def provider_choices():
    return [(key, p.label) for key, p in PROVIDERS.items()]
