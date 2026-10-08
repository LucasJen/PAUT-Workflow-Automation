"""
Providers that speak OpenAI's Chat Completions API, through the official `openai` package: OpenAI
itself, Google Gemini (its OpenAI-compatible endpoint) and Ollama, which runs models on this PC.
They differ only in address, whether a key is needed, and which models they list.

Answers stream; tool calls arrive in pieces (id and name first, then the arguments' JSON in
fragments) and are put back together by their index.
"""
import json
from decimal import Decimal

from .base import ModelInfo, Provider, ProviderError, Reply, TextDelta, ToolCall, Usage

STOPS = {'stop': 'end', 'tool_calls': 'tool_use', 'function_call': 'tool_use', 'length': 'max_tokens',
         'content_filter': 'refusal'}


def _sdk():
    try:
        import openai
    except ImportError as e:  # pragma: no cover - installed with requirements.txt
        raise ProviderError('The openai package is missing: pip install -r requirements.txt') from e
    return openai


class OpenAICompatibleProvider(Provider):
    base_url = None                       # None: OpenAI's own
    model_prefixes = ()                   # only list models starting with one of these ('' = all)
    unreachable = 'Couldn\'t reach {label}. Check the internet connection.'

    def __init__(self, base_url=None):
        if base_url:
            self.base_url = base_url

    def _client(self, api_key):
        if self.needs_key and not api_key:
            raise ProviderError(f'Add your {self.label} API key in Preferences › Assistant.')
        return _sdk().OpenAI(api_key=api_key or 'not-needed', base_url=self.base_url, max_retries=2)

    def _error(self, e):
        openai = _sdk()
        if isinstance(e, openai.AuthenticationError):
            return ProviderError(f'{self.label} rejected the API key. Check it in Preferences › Assistant.')
        if isinstance(e, openai.PermissionDeniedError):
            return ProviderError('This API key isn\'t allowed to use that model.')
        if isinstance(e, openai.NotFoundError):
            return ProviderError(f'{self.label} doesn\'t have that model. Pick another in Preferences › Assistant.')
        if isinstance(e, openai.RateLimitError):
            return ProviderError(f'{self.label}\'s rate limit or quota was reached. Wait a minute and ask again.')
        if isinstance(e, openai.BadRequestError):
            return ProviderError(f'{self.label} rejected the request: {e.message}')
        if isinstance(e, openai.APIStatusError):
            return ProviderError(f'{self.label} returned an error ({e.status_code}). Try again shortly.')
        if isinstance(e, openai.APIConnectionError):
            return ProviderError(self.unreachable.format(label=self.label))
        return ProviderError(str(e))

    def _keep(self, model_id):
        return not self.model_prefixes or model_id.startswith(self.model_prefixes)

    def models(self, api_key=None):
        if self.needs_key and not api_key:
            return list(self.known_models())
        try:
            listed = [m.id for m in self._client(api_key).models.list()]
        except Exception as e:
            raise self._error(e) from e
        known = {m.id: m for m in self.known_models()}
        ids = sorted({i.removeprefix('models/') for i in listed if self._keep(i.removeprefix('models/'))})
        return [known.get(i) or ModelInfo(i, i) for i in ids] or list(self.known_models())

    def check_key(self, api_key):
        self.models(api_key)

    def user_message(self, text):
        return {'role': 'user', 'content': text}

    def assistant_text(self, text):
        return {'role': 'assistant', 'content': text}

    def tool_results_messages(self, results):
        return [{'role': 'tool', 'tool_call_id': call_id, 'content': f'Error: {text}' if error else text}
                for call_id, text, error in results]

    def respond(self, api_key, model, system, messages, tools):
        client = self._client(api_key)
        params = {
            'model': model, 'stream': True, 'stream_options': {'include_usage': True},
            'messages': [{'role': 'system', 'content': system}, *messages],
            'tools': [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                                        'parameters': t['input_schema']}} for t in tools],
        }
        text, calls, finish, usage = [], {}, None, Usage()
        try:
            for chunk in client.chat.completions.create(**params):
                if chunk.usage:
                    usage = _usage(chunk.usage)
                for choice in chunk.choices or []:
                    delta = choice.delta
                    if delta and delta.content:
                        text.append(delta.content)
                        yield TextDelta(delta.content)
                    for piece in (delta.tool_calls or []) if delta else []:
                        call = calls.setdefault(piece.index, {'id': '', 'name': '', 'arguments': ''})
                        call['id'] = piece.id or call['id']
                        if piece.function:
                            call['name'] += piece.function.name or ''
                            call['arguments'] += piece.function.arguments or ''
                    finish = choice.finish_reason or finish
        except Exception as e:
            raise self._error(e) from e

        ordered = [calls[i] for i in sorted(calls)]
        for n, call in enumerate(ordered):
            call['id'] = call['id'] or f'call_{n}'      # some servers leave ids out
        message = {'role': 'assistant', 'content': ''.join(text) or None}
        if ordered:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function',
                                      'function': {'name': c['name'], 'arguments': c['arguments'] or '{}'}}
                                     for c in ordered]
        tool_calls = [ToolCall(c['id'], c['name'], _arguments(c['arguments'])) for c in ordered]
        stop = 'tool_use' if tool_calls and finish != 'length' else STOPS.get(finish, 'end')
        yield Reply(message=message, text=''.join(text), tool_calls=tool_calls, stop=stop, usage=usage, model=model)


def _arguments(raw):
    """The tool input; text that isn't a JSON object is passed on as-is for the tool to reject."""
    try:
        value = json.loads(raw or '{}')
    except ValueError:
        return raw
    return value


def _usage(usage):
    cached = getattr(getattr(usage, 'prompt_tokens_details', None), 'cached_tokens', None) or 0
    return Usage(input_tokens=max((usage.prompt_tokens or 0) - cached, 0), output_tokens=usage.completion_tokens or 0,
                 cache_read_tokens=cached)


class OpenAIProvider(OpenAICompatibleProvider):
    key = 'openai'
    label = 'OpenAI'
    default_model = 'gpt-5-mini'
    model_prefixes = ('gpt-', 'o1', 'o3', 'o4', 'chatgpt-')
    key_help = 'Create one at platform.openai.com › API keys.'
    privacy_note = 'OpenAI doesn\'t train its models on API data by default.'


class GoogleProvider(OpenAICompatibleProvider):
    key = 'google'
    label = 'Google Gemini'
    base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/'
    default_model = 'gemini-2.5-flash'
    model_prefixes = ('gemini-',)
    key_help = 'Create a free key at aistudio.google.com › Get API key.'
    privacy_note = ('On Google\'s free tier, what is sent may be used to improve Google\'s products: use it for '
                    'testing, not client data. Paid (billing enabled) keys aren\'t used that way.')


class OllamaProvider(OpenAICompatibleProvider):
    key = 'ollama'
    label = 'Ollama (local)'
    needs_key = False
    default_model = 'qwen2.5:7b'
    unreachable = 'Ollama isn\'t running on this PC. Start it from the Start menu (or check its address in Preferences).'
    key_help = 'Runs models on this PC: install Ollama from ollama.com, then download a model, e.g. run: ollama pull qwen2.5:7b'
    privacy_note = 'Everything stays on this PC. Answers are slower and less thorough than the cloud models.'

    def __init__(self, base_url=None):
        address = (base_url or 'http://localhost:11434').rstrip('/')
        super().__init__(address if address.endswith('/v1') else address + '/v1')

    def cost(self, model, usage):
        return Decimal('0')
