"""
The language model providers the assistant can use, by key (Preferences › Assistant lists them).
get_provider builds one for the saved settings (Ollama's address comes from them).
"""
from .anthropic_provider import AnthropicProvider
from .base import ModelInfo, Provider, ProviderError, Reply, TextDelta, ToolCall, Usage  # noqa: F401
from .openai_compatible import GoogleProvider, OllamaProvider, OpenAIProvider

PROVIDER_CLASSES = {cls.key: cls for cls in (AnthropicProvider, OpenAIProvider, GoogleProvider, OllamaProvider)}
DEFAULT_PROVIDER = 'anthropic'


def get_provider(key, settings=None):
    cls = PROVIDER_CLASSES.get(key) or PROVIDER_CLASSES[DEFAULT_PROVIDER]
    if cls is OllamaProvider:
        return cls(getattr(settings, 'ollama_url', None))
    return cls()


def provider_choices():
    return [(key, cls.label) for key, cls in PROVIDER_CLASSES.items()]
