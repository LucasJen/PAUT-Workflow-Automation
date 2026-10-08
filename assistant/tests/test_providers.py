"""OpenAI, Google Gemini and Ollama (the OpenAI-compatible adapter), per-provider settings and switching."""
import importlib
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta, ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction

from assistant import chat
from assistant.models import AssistantSettings, Conversation, Turn
from assistant.providers import get_provider, provider_choices
from assistant.providers.base import Usage
from assistant.providers.openai_compatible import GoogleProvider, OllamaProvider, OpenAIProvider
from assistant.tests.helpers import ScriptedProvider


def chunk(content=None, tool=None, finish=None, usage=None):
    tool_calls = None
    if tool:
        index, call_id, name, arguments = tool
        tool_calls = [ChoiceDeltaToolCall(index=index, id=call_id, type='function' if call_id else None,
                                          function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments))]
    choices = [] if usage else [Choice(index=0, delta=ChoiceDelta(content=content, tool_calls=tool_calls),
                                       finish_reason=finish)]
    return ChatCompletionChunk(id='c', object='chat.completion.chunk', created=0, model='m', choices=choices,
                               usage=usage)


def fake_client(chunks):
    create = mock.Mock(return_value=iter(chunks))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


class OpenAICompatibleTests(TestCase):
    def run_provider(self, provider, chunks, model='gpt-5-mini'):
        client, create = fake_client(chunks)
        with mock.patch.object(provider, '_client', return_value=client):
            events = list(provider.respond('key', model, 'system prompt',
                                           [provider.user_message('Hi')],
                                           [{'name': 'search', 'description': 'd', 'input_schema': {'type': 'object'}}]))
        return events, create.call_args.kwargs

    def test_streams_text_and_reads_usage(self):
        usage = CompletionUsage(prompt_tokens=1500, completion_tokens=40, total_tokens=1540,
                                prompt_tokens_details={'cached_tokens': 1000})
        events, params = self.run_provider(OpenAIProvider(), [
            chunk('Hel'), chunk('lo.'), chunk(finish='stop'), chunk(usage=usage)])
        self.assertEqual([e.text for e in events[:-1]], ['Hel', 'lo.'])
        reply = events[-1]
        self.assertEqual((reply.text, reply.stop, reply.tool_calls), ('Hello.', 'end', []))
        self.assertEqual((reply.usage.input_tokens, reply.usage.cache_read_tokens, reply.usage.output_tokens),
                         (500, 1000, 40))
        self.assertEqual(reply.message, {'role': 'assistant', 'content': 'Hello.'})
        self.assertEqual(params['messages'][0], {'role': 'system', 'content': 'system prompt'})
        self.assertEqual(params['tools'][0]['function']['name'], 'search')
        self.assertEqual(params['stream_options'], {'include_usage': True})

    def test_a_tool_call_in_pieces_is_put_back_together(self):
        events, _ = self.run_provider(GoogleProvider(), [
            chunk(tool=(0, 'call_1', 'search', '{"que')), chunk(tool=(0, None, None, 'ry": "11V58B"}')),
            chunk(tool=(1, 'call_2', 'open_report', '{"report_id": 7}')), chunk(finish='tool_calls')],
            model='gemini-2.5-flash')
        reply = events[-1]
        self.assertEqual(reply.stop, 'tool_use')
        self.assertEqual([(c.id, c.name, c.input) for c in reply.tool_calls],
                         [('call_1', 'search', {'query': '11V58B'}), ('call_2', 'open_report', {'report_id': 7})])
        self.assertEqual(reply.message['tool_calls'][0]['function'], {'name': 'search', 'arguments': '{"query": "11V58B"}'})
        self.assertIsNone(reply.message['content'])

    def test_missing_ids_bad_json_and_stops(self):
        events, _ = self.run_provider(OllamaProvider(), [chunk(tool=(0, None, 'search', '{"query": ')),
                                                         chunk(finish='stop')], model='qwen2.5:7b')
        call = events[-1].tool_calls[0]
        self.assertEqual((call.id, call.input), ('call_0', '{"query": '))   # the tool then reports bad input
        self.assertEqual(events[-1].stop, 'tool_use')
        self.assertEqual(self.run_provider(OpenAIProvider(), [chunk('x'), chunk(finish='length')])[0][-1].stop, 'max_tokens')
        self.assertEqual(self.run_provider(OpenAIProvider(), [chunk(finish='content_filter')])[0][-1].stop, 'refusal')

    def test_tool_results_are_one_message_each(self):
        self.assertEqual(OpenAIProvider().tool_results_messages([('a', 'found', False), ('b', 'no such report', True)]), [
            {'role': 'tool', 'tool_call_id': 'a', 'content': 'found'},
            {'role': 'tool', 'tool_call_id': 'b', 'content': 'Error: no such report'}])

    def test_providers_addresses_and_model_lists(self):
        self.assertEqual([k for k, _ in provider_choices()], ['anthropic', 'openai', 'google', 'ollama'])
        settings = AssistantSettings(ollama_url='http://10.0.0.5:11434/')
        self.assertEqual(get_provider('ollama', settings).base_url, 'http://10.0.0.5:11434/v1')
        self.assertFalse(get_provider('ollama').needs_key)
        self.assertEqual(get_provider('ollama').cost('qwen2.5:7b', Usage(input_tokens=10 ** 6)), Decimal('0'))
        google = GoogleProvider()
        listed = [SimpleNamespace(id='models/gemini-2.5-flash'), SimpleNamespace(id='models/text-embedding-004')]
        client = SimpleNamespace(models=SimpleNamespace(list=lambda: listed))
        with mock.patch.object(google, '_client', return_value=client):
            self.assertEqual([m.id for m in google.models('key')], ['gemini-2.5-flash'])


class SettingsTests(TestCase):
    def test_each_provider_keeps_its_own_key(self):
        settings = AssistantSettings.load()
        settings.api_key = 'sk-ant'
        settings.save()
        self.client.post(reverse('assistant-settings'), {'switch_provider': '1', 'provider': 'google'})
        settings = AssistantSettings.load()
        self.assertEqual((settings.provider, settings.model, settings.has_key), ('google', 'gemini-2.5-flash', False))
        page = self.client.get(reverse('assistant-settings'))
        self.assertContains(page, 'aistudio.google.com')
        self.assertContains(page, 'free tier')
        self.assertContains(page, 'name="input_price"')            # Gemini prices aren't built in
        with mock.patch.object(GoogleProvider, 'models', return_value=[]):
            self.client.post(reverse('assistant-settings'), {'provider': 'google', 'model': 'gemini-2.5-flash',
                                                             'api_key': 'AIza-test', 'input_price': '0.3',
                                                             'output_price': '2.5'})
        settings = AssistantSettings.load()
        self.assertEqual((settings.key_for('google'), settings.key_for('anthropic')), ('AIza-test', 'sk-ant'))
        self.assertEqual(settings.input_price, Decimal('0.3'))

    def test_ollama_needs_an_address_not_a_key(self):
        settings = AssistantSettings.load()
        settings.provider, settings.model = 'ollama', 'qwen2.5:7b'
        settings.save()
        page = self.client.get(reverse('assistant-settings'))
        self.assertContains(page, 'name="ollama_url"')
        self.assertNotContains(page, 'name="api_key"')
        self.assertContains(self.client.get(reverse('assistant')), 'name="question"')
        self.assertNotContains(self.client.get(reverse('assistant')), 'API key in')

    def test_entered_prices_cost_a_turn_when_the_model_has_none(self):
        settings = AssistantSettings(input_price=Decimal('2'), output_price=Decimal('8'))
        self.assertEqual(chat._cost(OpenAIProvider(), settings, 'gpt-x', Usage(input_tokens=10 ** 6, output_tokens=10 ** 6)),
                         Decimal('10'))
        self.assertIsNone(chat._cost(OpenAIProvider(), AssistantSettings(), 'gpt-x', Usage(input_tokens=1)))

    def test_the_old_single_key_moves_to_anthropic(self):
        migration = importlib.import_module('assistant.migrations.0002_per_provider_settings')
        row = SimpleNamespace(api_key_encrypted='dpapi:abc', model_list=[{'id': 'claude-haiku-4-5', 'label': 'Haiku'}],
                              api_keys={}, model_lists={}, save=mock.Mock())
        apps = SimpleNamespace(get_model=lambda *a: SimpleNamespace(objects=SimpleNamespace(all=lambda: [row])))
        migration.copy_key_and_models(apps, None)
        self.assertEqual(row.api_keys, {'anthropic': 'dpapi:abc'})
        self.assertEqual(row.model_lists['anthropic'][0]['id'], 'claude-haiku-4-5')
        row.save.assert_called_once()


class SwitchingProvidersTests(TestCase):
    def test_a_conversation_continues_on_another_provider_as_plain_text(self):
        settings = AssistantSettings.load()
        settings.provider, settings.model = 'ollama', 'qwen2.5:7b'
        settings.save()
        conversation = Conversation.objects.create(provider='anthropic')
        Turn.objects.create(conversation=conversation, question='What is on 11V58B?', answer='Report #67.',
                            provider='anthropic', model='claude-haiku-4-5',
                            transcript=[{'role': 'user', 'content': [{'type': 'text', 'text': 'What is on 11V58B?'}]}])
        provider = ScriptedProvider(('text', 'Done.'))
        provider.key = 'ollama'
        provider.needs_key = False
        with mock.patch('assistant.chat.get_provider', return_value=provider):
            events = list(chat.ask(conversation, 'And the thickness?'))
        self.assertEqual(events[-1]['type'], 'done')
        self.assertEqual(provider.requests[0][:2], [{'role': 'user', 'text': 'What is on 11V58B?'},
                                                    {'role': 'assistant', 'text': 'Report #67.'}])
