"""
What the chat needs from a language model provider. The chat engine (assistant/chat.py), the tools
and the settings page only use this interface, so adding another provider (OpenAI, a local model,
...) is a new module here registered in providers/__init__.py.

Transcripts are kept in the provider's own message format (each provider replays its own exactly,
which keeps prompt caching and model reasoning valid); `plain_history` turns another provider's
turns into plain question / answer text.
"""
from dataclasses import dataclass, field
from decimal import Decimal


class ProviderError(Exception):
    """A request failed in a way the person should see (bad key, rate limit, no connection, ...)."""


@dataclass
class ModelInfo:
    id: str
    label: str
    input_price: Decimal = None       # USD per million tokens; None: unknown
    output_price: Decimal = None


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other):
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


@dataclass
class TextDelta:
    """Part of the answer as it is written."""
    text: str


@dataclass
class Reply:
    """One finished model response: its message to append to the transcript, and what it asks for."""
    message: dict                     # provider-format assistant message
    text: str
    tool_calls: list = field(default_factory=list)
    stop: str = 'end'                 # 'end', 'tool_use', 'max_tokens' or 'refusal'
    usage: Usage = field(default_factory=Usage)
    model: str = ''                   # the model that answered (a fallback model after a refusal)


class Provider:
    key = ''
    label = ''
    default_model = ''

    def models(self, api_key=None):
        """[ModelInfo] the person can pick from (the live list when the key allows, else the known ones)."""
        raise NotImplementedError

    def check_key(self, api_key):
        """Raises ProviderError when the key doesn't work."""
        raise NotImplementedError

    def respond(self, api_key, model, system, messages, tools):
        """
        Streams one response: yields TextDelta as the answer is written, then the Reply. `messages`
        is the provider-format transcript; `tools` the neutral tool definitions (name, description,
        input_schema).
        """
        raise NotImplementedError

    def user_message(self, text):
        raise NotImplementedError

    def assistant_text(self, text):
        raise NotImplementedError

    def tool_results_message(self, results):
        """The message answering tool calls: results [(tool call id, text, is_error)]."""
        raise NotImplementedError

    def cost(self, model, usage):
        """Estimated USD for the usage, or None when the model's price isn't known."""
        info = next((m for m in self.known_models() if m.id == model), None)
        if info is None or info.input_price is None:
            return None
        per = Decimal(1_000_000)
        return (Decimal(usage.input_tokens) * info.input_price
                + Decimal(usage.cache_write_tokens) * info.input_price * Decimal('1.25')
                + Decimal(usage.cache_read_tokens) * info.input_price * Decimal('0.1')
                + Decimal(usage.output_tokens) * info.output_price) / per

    def known_models(self):
        return []


def plain_history(turns, provider):
    """Earlier turns as plain question / answer messages in `provider`'s format (for a provider switch)."""
    messages = []
    for turn in turns:
        if turn.answer:
            messages.append(provider.user_message(turn.question))
            messages.append(provider.assistant_text(turn.answer))
    return messages
