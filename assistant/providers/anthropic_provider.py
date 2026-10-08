"""
Claude, through the official Anthropic SDK (pip package `anthropic`).

Responses stream (the answer appears as it is written); the system prompt and transcript are
cached (`cache_control`) so a conversation's earlier turns cost a tenth on later questions. Claude
Sonnet 5.5 / Opus 5.5 get an explicit effort and the server-side refusal fallback; Claude Haiku 4.5
takes neither.
"""
from decimal import Decimal

from .base import ModelInfo, Provider, ProviderError, Reply, TextDelta, ToolCall, Usage

MAX_TOKENS = 32000

# Prices are USD per million tokens (input, output)
KNOWN_MODELS = [
    ModelInfo('claude-haiku-4-5', 'Claude Haiku 4.5 (fast, lowest cost)', Decimal('1'), Decimal('5')),
    ModelInfo('claude-sonnet-5-5', 'Claude Sonnet 5.5', Decimal('2'), Decimal('10')),
    ModelInfo('claude-opus-5-5', 'Claude Opus 5.5 (most capable)', Decimal('4'), Decimal('20')),
]
# Models that take output_config.effort and the server-side refusal fallback
EFFORT_MODELS = {'claude-sonnet-5-5': 'medium', 'claude-opus-5-5': 'medium'}
FALLBACK_BETA = 'server-side-fallback-2026-07-01'


def _sdk():
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - installed with requirements.txt
        raise ProviderError('The anthropic package is missing: pip install -r requirements.txt') from e
    return anthropic


def _error(e):
    """A ProviderError the person can act on, from an SDK exception."""
    anthropic = _sdk()
    if isinstance(e, anthropic.AuthenticationError):
        return ProviderError('Anthropic rejected the API key. Check it in Preferences › Assistant.')
    if isinstance(e, anthropic.PermissionDeniedError):
        return ProviderError('This API key isn\'t allowed to use that model.')
    if isinstance(e, anthropic.NotFoundError):
        return ProviderError('Anthropic doesn\'t know that model. Pick another in Preferences › Assistant.')
    if isinstance(e, anthropic.RateLimitError):
        return ProviderError('Anthropic\'s rate limit was reached. Wait a minute and ask again.')
    if isinstance(e, anthropic.BadRequestError):
        return ProviderError(f'Anthropic rejected the request: {e.message}')
    if isinstance(e, anthropic.APIStatusError):
        return ProviderError(f'Anthropic returned an error ({e.status_code}). Try again shortly.')
    if isinstance(e, anthropic.APIConnectionError):
        return ProviderError('Couldn\'t reach Anthropic. Check the internet connection.')
    return ProviderError(str(e))


def _usage(usage):
    return Usage(input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0,
                 cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
                 cache_write_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0)


def _without_fallback_blocks(message):
    content = message.get('content')
    if isinstance(content, list) and any(b.get('type') == 'fallback' for b in content):
        return {**message, 'content': [b for b in content if b.get('type') != 'fallback']}
    return message


STOPS = {'end_turn': 'end', 'stop_sequence': 'end', 'tool_use': 'tool_use', 'max_tokens': 'max_tokens',
         'refusal': 'refusal', 'pause_turn': 'pause'}


class AnthropicProvider(Provider):
    key = 'anthropic'
    label = 'Anthropic (Claude)'
    default_model = 'claude-haiku-4-5'
    key_help = 'Create one at console.anthropic.com › API keys.'
    privacy_note = 'Anthropic doesn\'t train its models on API data.'

    def known_models(self):
        return KNOWN_MODELS

    def _client(self, api_key):
        if not api_key:
            raise ProviderError('Add an Anthropic API key in Preferences › Assistant.')
        return _sdk().Anthropic(api_key=api_key, max_retries=2)

    def models(self, api_key=None):
        """Claude models the key can use, newest first, priced where known; the known list without a key."""
        if not api_key:
            return list(KNOWN_MODELS)
        try:
            listed = list(self._client(api_key).models.list())
        except Exception as e:
            raise _error(e) from e
        known = {m.id: m for m in KNOWN_MODELS}
        out = [known.get(m.id) or ModelInfo(m.id, m.display_name) for m in listed]
        return out or list(KNOWN_MODELS)

    def check_key(self, api_key):
        self.models(api_key)

    def user_message(self, text):
        return {'role': 'user', 'content': [{'type': 'text', 'text': text}]}

    def assistant_text(self, text):
        return {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}

    def tool_results_messages(self, results):
        return [{'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': call_id, 'content': text, **({'is_error': True} if error else {})}
            for call_id, text, error in results]}]

    def respond(self, api_key, model, system, messages, tools):
        client = self._client(api_key)
        params = {
            'model': model, 'max_tokens': MAX_TOKENS, 'system': system, 'messages': messages,
            # Caches the system prompt, tools and transcript: later questions re-read them at a tenth of the price
            'cache_control': {'type': 'ephemeral'},
            'tools': [{**tool, 'eager_input_streaming': True} for tool in tools],
        }
        effort = EFFORT_MODELS.get(model)
        if effort:
            params['output_config'] = {'effort': effort}
            # Server-side refusal fallback: a declined request is re-run on a fallback model in the same call
            stream = client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks='default', **params)
        else:
            # A fallback block (from a Sonnet / Opus turn earlier in the conversation) is beta-only
            params['messages'] = [_without_fallback_blocks(m) for m in messages]
            stream = client.messages.stream(**params)
        try:
            with stream as events:
                for event in events:
                    if event.type == 'text':
                        yield TextDelta(event.text)
                final = events.get_final_message()
        except ValueError as e:   # a tool input the SDK couldn't parse at all
            raise ProviderError('Claude sent a tool request that couldn\'t be read; ask again.') from e
        except Exception as e:
            raise _error(e) from e

        tool_calls = [ToolCall(b.id, b.name, b.input) for b in final.content if b.type == 'tool_use']
        text = ''.join(b.text for b in final.content if b.type == 'text')
        # The message exactly as Claude sent it (thinking, fallback and tool blocks included): replayed unchanged
        message = {'role': 'assistant', 'content': [b.to_dict(exclude_none=True) for b in final.content]}
        yield Reply(message=message, text=text, tool_calls=tool_calls, stop=STOPS.get(final.stop_reason, 'end'),
                    usage=_usage(final.usage), model=getattr(final, 'model', model) or model)
