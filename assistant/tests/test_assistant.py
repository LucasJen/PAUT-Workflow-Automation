"""The assistant: key storage, the search index, the look-up tools, the chat loop and the pages."""
import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

import anthropic.types as sdk
from assistant import chat, index, secrets
from assistant.models import AssistantSettings, Conversation, Turn
from assistant.providers.anthropic_provider import AnthropicProvider, FALLBACK_BETA
from assistant.providers.base import TextDelta, Usage
from assistant.tests.helpers import ScriptedProvider, text_pdf
from assistant.tools import Lookup
from documents.models import Document
from reports.models import Report, Setup


class MediaTestCase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def library(self):
        """A report, its setup, a saved setup and a two-page procedure."""
        self.report = Report.objects.create(
            report_type='paut_corrosion', document_filename='2026-03-PAUT-Corrosion-11V58B', equipment_id='11V58B',
            client='Flint Hills Resources', location='Rosemount, MN', test_date=date(2026, 3, 11),
            executive_summary='Minimum thickness 0.312 in on the bottom head; no significant corrosion.')
        self.setup = Setup.objects.create(report=self.report, title='HydroFORM', transducer_model='7.5L64-I4',
                                          scope_model='OmniScan X3', scope_serial='QC-0030383')
        self.saved = Setup.objects.create(title='Angle Beam', transducer_model='5L64-A32')
        self.document = Document.objects.create(
            category=Document.PROCEDURE, title='100-UT-031', description='HydroForm thickness mapping',
            file=SimpleUploadedFile('100-UT-031.pdf', text_pdf('Scope of the procedure',
                                                               'Calibration on a step wedge before scanning')))


class SecretsTests(TestCase):
    def test_the_key_is_stored_encrypted_and_reads_back(self):
        settings = AssistantSettings.load()
        settings.api_key = 'sk-ant-test-123'
        settings.save()
        stored = AssistantSettings.objects.get().api_keys['anthropic']
        self.assertNotIn('sk-ant-test-123', stored)
        self.assertTrue(stored.startswith(('dpapi:', 'plain:')))
        self.assertEqual(AssistantSettings.load().api_key, 'sk-ant-test-123')

    def test_a_key_from_another_pc_asks_to_enter_it_again(self):
        if secrets.win32crypt is None:
            self.skipTest('DPAPI is Windows only')
        with self.assertRaises(secrets.SecretError):
            secrets.decrypt('dpapi:' + 'AAAA')


class IndexTests(MediaTestCase):
    def test_finds_reports_setups_and_pdf_pages(self):
        self.library()
        self.assertEqual(index.sync(), 4)
        self.assertEqual(index.stats(), {'report': 1, 'setup': 2, 'document': 1, 'pages': 2})
        hit = index.search('11V58B corrosion')[0]
        self.assertEqual((hit['kind'], hit['id']), ('report', self.report.pk))
        self.assertEqual([(h['kind'], h['id']) for h in index.search('QC-0030383', 'setup')],
                         [('setup', self.setup.pk)])
        page = index.search('step wedge calibration', 'document')[0]
        self.assertEqual((page['id'], page['page']), (self.document.pk, 2))
        self.assertIn('[', page['snippet'])
        self.assertEqual(index.search('100-UT-031')[0]['kind'], 'document')
        self.assertEqual(index.search('zzzqqq'), [])

    def test_only_what_changed_is_read_again(self):
        self.library()
        index.sync()
        self.assertEqual(index.sync(), 0)
        self.report.executive_summary = 'Pitting found on the shell'
        self.report.save()
        self.assertEqual(index.sync(), 1)
        self.assertEqual(index.search('pitting')[0]['id'], self.report.pk)
        self.saved.delete()
        self.assertEqual(index.sync(), 1)
        self.assertEqual(index.search('5L64-A32'), [])

    def test_an_unchanged_library_is_not_read_again(self):
        self.library()
        index.sync()
        with mock.patch('assistant.sources.report_text', side_effect=AssertionError('read again')),                 mock.patch('assistant.sources.setup_text', side_effect=AssertionError('read again')):
            self.assertEqual(index.sync(), 0)
        # Saved without a change to its text: only its stamp moves
        self.report.save()
        self.assertEqual(index.sync(), 0)
        with mock.patch('assistant.sources.report_text', side_effect=AssertionError('read again')):
            self.assertEqual(index.sync(), 0)

    def test_a_setup_edited_on_its_own_page_reindexes_its_report(self):
        self.library()
        index.sync()
        Setup.objects.filter(pk=self.setup.pk).update(transducer_model='7.5L60-PWZ1')   # no report save
        self.assertEqual(index.sync(), 2)   # the setup and its report
        self.assertEqual({h['kind'] for h in index.search('7.5L60-PWZ1')}, {'setup', 'report'})


class ToolTests(MediaTestCase):
    def test_lookups_return_text_and_record_their_sources(self):
        self.library()
        index.sync()
        lookup = Lookup()
        text, error = lookup.run('search', {'query': 'HydroForm'})
        self.assertFalse(error)
        self.assertIn(f'report #{self.report.pk}', text)
        text, _ = lookup.run('open_report', {'report_id': self.report.pk})
        self.assertIn('Minimum thickness 0.312 in', text)
        self.assertIn(f'Setup #{self.setup.pk}', text)
        text, _ = lookup.run('read_document', {'document_id': self.document.pk, 'first_page': 2})
        self.assertIn('--- Page 2 of 2 ---', text)
        self.assertIn('step wedge', text)
        text, _ = lookup.run('list_reports', {'text': 'Flint', 'date_from': '2026-01-01'})
        self.assertIn('1 reports', text)
        self.assertEqual([s['label'] for s in lookup.links()],
                         [f'Report #{self.report.pk} · 2026-03-PAUT-Corrosion-11V58B', '100-UT-031 · HydroForm thickness mapping'])
        self.assertEqual(len(lookup.steps), 4)

    def test_bad_input_comes_back_as_an_error_for_the_model(self):
        lookup = Lookup()
        self.assertEqual(lookup.run('open_report', {'report_id': 'seven'}), ('report_id must be a whole number.', True))
        self.assertEqual(lookup.run('open_report', {'report_id': 999}), ('There is no report with that id.', True))
        self.assertEqual(lookup.run('delete_everything', {})[1], True)
        self.assertEqual(lookup.run('list_reports', {'date_from': 'March'})[1], True)


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ChatTests(TestCase):
    def setUp(self):
        settings = AssistantSettings.load()
        settings.provider, settings.model = 'scripted', 'scripted-1'
        settings.api_key = 'key'      # saved for the provider in use
        settings.save()
        self.report = Report.objects.create(equipment_id='11V58B', executive_summary='No corrosion found.')

    def run_chat(self, provider, question, conversation=None):
        conversation = conversation or Conversation.objects.create()
        with mock.patch('assistant.chat.get_provider', return_value=provider):
            events = list(chat.ask(conversation, question))
        return conversation, events

    def test_looks_up_then_answers_and_saves_the_turn(self):
        provider = ScriptedProvider(('tool', 'open_report', {'report_id': self.report.pk}),
                                    ('text', 'No corrosion was found on 11V58B (report #1).'))
        conversation, events = self.run_chat(provider, 'Summarize 11V58B')
        kinds = [e['type'] for e in events]
        self.assertIn('step', kinds)
        self.assertEqual(kinds[-1], 'done')
        self.assertEqual(''.join(e['text'] for e in events if e['type'] == 'text').strip(),
                         'No corrosion was found on 11V58B (report #1).')
        turn = Turn.objects.get()
        self.assertEqual(turn.status, Turn.OK)
        self.assertEqual(len(turn.transcript), 4)        # question, tool call, tool result, answer
        self.assertEqual(turn.sources[0]['url'], f"{reverse('create-report')}?loaded={self.report.pk}")
        self.assertEqual(turn.cost, Decimal('0.0030'))    # 2 × (1000 in × $1 + 100 out × $5) per million
        self.assertIn('<p>No corrosion', turn.answer_html)
        self.assertEqual(conversation.title, 'Summarize 11V58B')

    def test_later_questions_replay_the_conversation(self):
        first = ScriptedProvider(('text', 'Answer one.'))
        conversation, _ = self.run_chat(first, 'Question one')
        second = ScriptedProvider(('text', 'Answer two.'))
        self.run_chat(second, 'Question two', conversation)
        sent = second.requests[0]
        self.assertEqual([m['role'] for m in sent], ['user', 'assistant', 'user'])
        self.assertTrue(sent[0]['text'].startswith('Question one'))

    def test_a_failed_turn_is_kept_but_not_replayed(self):
        conversation, events = self.run_chat(ScriptedProvider(('error', 'Anthropic rejected the API key.')), 'Hi')
        self.assertEqual(events[-1], {'type': 'error', 'text': 'Anthropic rejected the API key.'})
        self.assertEqual(Turn.objects.get().status, Turn.ERROR)
        provider = ScriptedProvider(('text', 'Hello.'))
        self.run_chat(provider, 'Hi again', conversation)
        self.assertEqual(len(provider.requests[0]), 1)

    def test_the_monthly_cap_stops_asking(self):
        settings = AssistantSettings.load()
        settings.monthly_cap = Decimal('0.01')
        settings.save()
        conversation = Conversation.objects.create()
        Turn.objects.create(conversation=conversation, question='q', provider='scripted', model='m', cost=Decimal('0.02'))
        _, events = self.run_chat(ScriptedProvider(), 'Another question', conversation)
        self.assertEqual(events[0]['type'], 'error')
        self.assertIn('spending cap', events[0]['text'])

    def test_no_key_no_request(self):
        settings = AssistantSettings.load()
        settings.api_key = ''
        settings.save()
        provider = ScriptedProvider()
        _, events = self.run_chat(provider, 'Hi')
        self.assertIn('API key', events[0]['text'])
        self.assertEqual(provider.requests, [])

    # Whatever goes wrong while answering is said and saved, never left on "Thinking..."
    def test_an_index_failure_is_an_error_event_and_a_saved_turn(self):
        with mock.patch('assistant.chat.index.sync', side_effect=OSError('disk unplugged')):
            _, events = self.run_chat(ScriptedProvider(('text', 'Never sent.')), 'Hi')
        self.assertEqual(events[-1], {'type': 'error', 'text': 'Something went wrong while answering: disk unplugged'})
        self.assertEqual(Turn.objects.get().status, Turn.ERROR)

    def test_a_stream_that_ends_without_its_reply_is_an_error(self):
        provider = ScriptedProvider(('text', 'Half'))
        provider.respond = lambda *args: iter([TextDelta('Half ')])
        _, events = self.run_chat(provider, 'Hi')
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('stopped before it finished', events[-1]['text'])

    def test_a_new_conversation_stopped_before_asking_isnt_kept(self):
        settings = AssistantSettings.load()
        settings.api_key = ''
        settings.save()
        response = self.client.post(reverse('assistant-ask'), {'question': 'Hi'})
        events = [json.loads(line) for line in b''.join(response.streaming_content).decode().splitlines()]
        self.assertEqual([e['type'] for e in events], ['error'])
        self.assertFalse(Conversation.objects.exists())


def sdk_message(model='claude-haiku-4-5', content=None, stop='end_turn'):
    return sdk.Message(id='msg_1', type='message', role='assistant', model=model, stop_reason=stop,
                       stop_sequence=None, content=content or [sdk.TextBlock(type='text', text='Hello', citations=None)],
                       usage=sdk.Usage(input_tokens=1200, output_tokens=80, cache_read_input_tokens=4000,
                                       cache_creation_input_tokens=0))


class FakeStream:
    def __init__(self, final, texts):
        self.final, self.texts = final, texts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(SimpleNamespace(type='text', text=t) for t in self.texts)

    def get_final_message(self):
        return self.final


class AnthropicProviderTests(TestCase):
    def fake_client(self, final, texts=('Hel', 'lo')):
        stream = mock.Mock(return_value=FakeStream(final, list(texts)))
        client = SimpleNamespace(messages=SimpleNamespace(stream=stream),
                                 beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
        return client, stream

    def test_haiku_streams_text_and_keeps_the_reply_as_sent(self):
        provider = AnthropicProvider()
        client, stream = self.fake_client(sdk_message())
        with mock.patch.object(provider, '_client', return_value=client):
            events = list(provider.respond('key', 'claude-haiku-4-5', 'system', [provider.user_message('Hi')], []))
        self.assertEqual([e.text for e in events[:-1]], ['Hel', 'lo'])
        reply = events[-1]
        self.assertEqual(reply.message, {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Hello'}]})
        self.assertEqual((reply.stop, reply.usage.cache_read_tokens), ('end', 4000))
        params = stream.call_args.kwargs
        self.assertNotIn('output_config', params)
        self.assertNotIn('betas', params)
        self.assertEqual(params['cache_control'], {'type': 'ephemeral'})

    def test_sonnet_and_opus_get_effort_and_the_refusal_fallback(self):
        provider = AnthropicProvider()
        tool = sdk.ToolUseBlock(type='tool_use', id='tu_1', name='search', input={'query': '11V58B'})
        client, stream = self.fake_client(sdk_message('claude-opus-5-5', [tool], 'tool_use'), texts=())
        tools = [{'name': 'search', 'description': 'd', 'input_schema': {'type': 'object'}}]
        with mock.patch.object(provider, '_client', return_value=client):
            reply = list(provider.respond('key', 'claude-opus-5-5', 'system', [], tools))[-1]
        params = stream.call_args.kwargs
        self.assertEqual((params['betas'], params['fallbacks']), ([FALLBACK_BETA], 'default'))
        self.assertEqual(params['output_config'], {'effort': 'medium'})
        self.assertTrue(params['tools'][0]['eager_input_streaming'])
        self.assertEqual((reply.stop, reply.tool_calls[0].input), ('tool_use', {'query': '11V58B'}))

    def test_tool_results_and_cost(self):
        provider = AnthropicProvider()
        self.assertEqual(provider.tool_results_messages([('tu_1', 'found', False), ('tu_2', 'bad', True)]),
                         [{'role': 'user', 'content': [
                             {'type': 'tool_result', 'tool_use_id': 'tu_1', 'content': 'found'},
                             {'type': 'tool_result', 'tool_use_id': 'tu_2', 'content': 'bad', 'is_error': True}]}])
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000)
        self.assertEqual(provider.cost('claude-haiku-4-5', usage), Decimal('6.1'))
        self.assertIsNone(provider.cost('claude-some-future-model', usage))


class PageTests(MediaTestCase):
    def test_settings_save_the_key_encrypted_and_list_the_models(self):
        with mock.patch.object(AnthropicProvider, 'models', return_value=AnthropicProvider().known_models()):
            response = self.client.post(reverse('assistant-settings'), {
                'provider': 'anthropic', 'model': 'claude-haiku-4-5', 'api_key': 'sk-ant-xyz', 'monthly_cap': '20'},
                follow=True)
        self.assertContains(response, 'Anthropic (Claude) works: 3 models available.')
        settings = AssistantSettings.load()
        self.assertEqual((settings.api_key, settings.monthly_cap), ('sk-ant-xyz', Decimal('20')))
        self.assertNotContains(response, 'sk-ant-xyz')
        # Saving again without typing the key keeps it
        self.client.post(reverse('assistant-settings'), {'provider': 'anthropic', 'model': 'claude-opus-5-5',
                                                         'monthly_cap': ''})
        settings = AssistantSettings.load()
        self.assertEqual((settings.api_key, settings.model, settings.monthly_cap), ('sk-ant-xyz', 'claude-opus-5-5', None))

    def test_rebuild_index_and_the_chat_page(self):
        self.library()
        response = self.client.post(reverse('assistant-settings'), {'rebuild_index': '1'}, follow=True)
        self.assertContains(response, '1 reports, 2 setups and 1 documents')
        page = self.client.get(reverse('assistant'))
        self.assertContains(page, 'Add your Anthropic (Claude) API key')
        self.assertContains(self.client.get(reverse('home')), reverse('assistant'))

    def test_ask_streams_events_and_opens_the_new_conversation(self):
        settings = AssistantSettings.load()
        settings.api_key = 'key'
        settings.save()
        with mock.patch('assistant.chat.get_provider', return_value=ScriptedProvider(('text', 'Hello there.'))):
            response = self.client.post(reverse('assistant-ask'), {'question': 'Hi'})
            events = [json.loads(line) for line in b''.join(response.streaming_content).decode().splitlines()]
        conversation = Conversation.objects.get()
        self.assertEqual(events[0], {'type': 'conversation', 'id': conversation.pk})
        self.assertEqual(events[-1]['type'], 'done')
        page = self.client.get(reverse('assistant-conversation', args=[conversation.pk]))
        self.assertContains(page, 'Hello there.')
        self.client.post(reverse('assistant-delete', args=[conversation.pk]))
        self.assertFalse(Conversation.objects.exists())
