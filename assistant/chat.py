"""
Answering a question: the model searches and opens what it needs (tools.py) until it can answer,
streaming the answer as it writes it. ask() yields events for the page (see EVENT kinds below) and
saves the turn. The conversation's earlier turns are replayed unchanged, so the model sees the
whole conversation, and its prompt cache keeps that cheap.

Events: {'type': 'status', 'text'}, {'type': 'step', 'text'}, {'type': 'text', 'text'},
{'type': 'done', 'html', 'sources', 'cost', 'conversation_cost', 'tokens', 'model'},
{'type': 'error', 'text'}.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from markdown_it import MarkdownIt

from . import index
from .models import AssistantSettings, Turn
from .providers import ProviderError, Reply, TextDelta, Usage, get_provider
from .providers.base import plain_history
from .tools import TOOLS, Lookup

MAX_ROUNDS = 10          # model responses per question (each may call tools)

# Fixed for every conversation (the prompt cache depends on it not changing): no dates or counts here
SYSTEM_PROMPT = """\
You are the assistant inside PAUT Report Automation, the app a Mistras Group phased array ultrasonic \
testing (PAUT) technician uses to write inspection reports. You answer questions about the app's own \
data: its reports (project details, results tables, executive summaries, notes), UT setups (instrument, \
probe, wedge and settings, many imported from OmniScan / MXU .nde files) and its document library \
(Mistras procedures and work instructions, code material, training material, report forms).

How to answer:
- Look things up before answering: use search, list_reports, open_report, open_setup and read_document. \
Search again with other words (an equipment ID, a procedure number, a client name, a technique) when a \
search misses. Open the items you rely on, rather than answering from search snippets alone.
- Answer from what you found, and say which report, setup or document each point comes from, with its \
reference (for example "report #68" or "100-UT-031, page 4").
- If the data doesn't answer the question, say so plainly. You may add general NDT knowledge (ASME, API, \
AWS codes, UT practice) only when it helps, and label it clearly as general knowledge, not from the app's \
records. Never invent readings, dates, serial numbers or findings.
- Thickness and length values keep the units the record gives them in.
- Be concise: lead with the answer, then the supporting detail. Use short lists or a table when \
comparing several reports or readings."""


def _markdown():
    return MarkdownIt('commonmark', {'html': False, 'linkify': False}).enable('table').enable('strikethrough')


def render(text):
    """The answer as HTML (Markdown with raw HTML disabled, so nothing from a record can inject markup)."""
    return _markdown().render(text or '')


def month_spend(today=None):
    today = today or timezone.localdate()
    start = today.replace(day=1)
    total = Turn.objects.filter(created_at__date__gte=start).aggregate(total=Sum('cost'))['total']
    return total or Decimal('0')


def _history(conversation, provider):
    """The earlier turns' messages: replayed unchanged from the same provider; as plain text from another."""
    turns = list(conversation.turns.filter(status=Turn.OK).order_by('created_at', 'pk'))
    if all(t.provider == provider.key for t in turns):
        return [m for t in turns for m in t.transcript]
    return plain_history(turns, provider)


def ask(conversation, question, settings=None):
    """Answers `question` in `conversation`, yielding page events; the turn is saved however it ends."""
    settings = settings or AssistantSettings.load()
    provider = get_provider(settings.provider)
    model = settings.model or provider.default_model
    turn = Turn(conversation=conversation, question=question, provider=provider.key, model=model)

    if settings.monthly_cap is not None and month_spend() >= settings.monthly_cap:
        yield {'type': 'error', 'text': f'This month\'s spending cap (${settings.monthly_cap}) has been reached. '
                                        'Raise it in Preferences › Assistant to keep asking.'}
        return
    try:
        api_key = settings.api_key
    except Exception as e:  # secrets.SecretError
        yield {'type': 'error', 'text': str(e)}
        return
    if not api_key:
        yield {'type': 'error', 'text': 'Add an API key in Preferences › Assistant first.'}
        return

    yield {'type': 'status', 'text': 'Checking for new or changed records…'}
    index.sync()

    if not conversation.title:
        conversation.title = question.strip().splitlines()[0][:120]
    conversation.provider = provider.key
    conversation.save()

    lookup = Lookup()
    usage = Usage()
    answer, cost = [], Decimal('0')
    cost_known = True
    # The question, with the date it was asked (appended, never edited: the transcript stays a valid prefix)
    transcript = [provider.user_message(f'{question}\n\n(Asked on {date.today():%Y-%m-%d}.)')]
    history = _history(conversation, provider)
    try:
        for _ in range(MAX_ROUNDS):
            reply = None
            yield {'type': 'status', 'text': 'Thinking…'}
            for event in provider.respond(api_key, model, SYSTEM_PROMPT, history + transcript, TOOLS):
                if isinstance(event, TextDelta):
                    answer.append(event.text)
                    yield {'type': 'text', 'text': event.text}
                elif isinstance(event, Reply):
                    reply = event
            transcript.append(reply.message)
            usage.add(reply.usage)
            part = provider.cost(reply.model or model, reply.usage)
            if part is None:
                cost_known = False
            else:
                cost += part
            if reply.stop == 'refusal':
                answer.append('\n\n*The model declined to answer this.*')
                break
            if reply.stop == 'max_tokens' and not reply.tool_calls:
                answer.append('\n\n*(The answer was cut short at the length limit.)*')
                break
            if not reply.tool_calls:
                break
            if reply.stop == 'max_tokens':   # a cut-off tool request can't be run
                raise ProviderError('The model\'s request was cut short; ask again.')
            results = []
            for call in reply.tool_calls:
                text, is_error = lookup.run(call.name, call.input)
                results.append((call.id, text, is_error))
                if lookup.steps:
                    yield {'type': 'step', 'text': lookup.steps[-1]}
            transcript.append(provider.tool_results_message(results))
            answer.append('\n\n')   # text written before a look-up stays, separated from what follows
        else:
            answer.append('\n\n*(Stopped after too many look-ups; ask a narrower question.)*')
    except ProviderError as e:
        turn.status, turn.transcript = Turn.ERROR, []
        turn.answer = str(e)
        _save(turn, usage, cost if cost_known else None, lookup)
        yield {'type': 'error', 'text': str(e)}
        return

    turn.answer = ''.join(answer).strip()
    turn.answer_html = render(turn.answer)
    turn.transcript = transcript
    _save(turn, usage, cost if cost_known else None, lookup)
    conversation.save()   # moves it to the top of the list
    yield {'type': 'done', 'html': turn.answer_html, 'sources': turn.sources, 'steps': turn.steps,
           'cost': _money(turn.cost), 'conversation_cost': _money(conversation.cost),
           'tokens': usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens + usage.output_tokens,
           'model': model, 'conversation': conversation.pk, 'title': conversation.title}


def _save(turn, usage, cost, lookup):
    turn.input_tokens, turn.output_tokens = usage.input_tokens, usage.output_tokens
    turn.cache_read_tokens, turn.cache_write_tokens = usage.cache_read_tokens, usage.cache_write_tokens
    turn.cost = cost
    turn.sources, turn.steps = lookup.links(), lookup.steps
    turn.save()


def _money(value):
    if value is None:
        return ''
    return f'${value:.4f}' if 0 < value < 1 else f'${value:.2f}'
