"""
The tools the model calls to look things up, defined once in a provider-neutral form (name,
description, JSON schema) and run here. Every result is plain text with the item's reference, and
is kept under MAX_CHARS so one look-up can't flood the conversation.
"""
from datetime import date

from django.db.models import Q

from reports.models import Report

from . import index, sources
from .sources import DOCUMENT, REPORT, SETUP

MAX_CHARS = 24000
MAX_PAGES = 10

TOOLS = [
    {
        'name': 'search',
        'description': (
            'Full-text search over the app\'s reports (project details, results tables, summaries, notes), UT '
            'setups (instrument, probe, wedge and settings) and library documents (procedures, code and training '
            'material, page by page). Matches words, including codes such as 100-UT-031, 11V58B or SA-516. '
            'Returns the best matches with a snippet and a reference to open. Search several times with '
            'different words when the first search misses.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Words to look for.'},
                'kind': {'type': 'string', 'enum': ['any', REPORT, SETUP, DOCUMENT],
                         'description': 'Only this kind of item (default any).'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'description': 'Matches to return (default 8).'},
            },
            'required': ['query'],
        },
    },
    {
        'name': 'list_reports',
        'description': (
            'Lists reports matching filters, newest test date first, with their main details: use it for '
            'questions about sets of reports (all reports for a client, a unit or a date range, counts).'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'text': {'type': 'string', 'description': 'Words in the client, location, equipment ID, '
                                                          'item description or file name.'},
                'report_type': {'type': 'string', 'description': 'Report type key or label, e.g. "Short Form".'},
                'date_from': {'type': 'string', 'description': 'Earliest test date, YYYY-MM-DD.'},
                'date_to': {'type': 'string', 'description': 'Latest test date, YYYY-MM-DD.'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
            },
        },
    },
    {
        'name': 'open_report',
        'description': 'The full text of one report: every filled-in field, people, results table, setups and image captions.',
        'input_schema': {'type': 'object', 'properties': {'report_id': {'type': 'integer'}}, 'required': ['report_id']},
    },
    {
        'name': 'open_setup',
        'description': 'Every setting of one UT setup (instrument, probe, wedge, UT settings, calibration, source .nde file).',
        'input_schema': {'type': 'object', 'properties': {'setup_id': {'type': 'integer'}}, 'required': ['setup_id']},
    },
    {
        'name': 'read_document',
        'description': (
            f'Reads pages of a library document (PDF text). Give the pages a search pointed at; at most '
            f'{MAX_PAGES} pages per call. Without pages it returns the document\'s details and first pages.'),
        'input_schema': {
            'type': 'object',
            'properties': {
                'document_id': {'type': 'integer'},
                'first_page': {'type': 'integer', 'minimum': 1},
                'last_page': {'type': 'integer', 'minimum': 1},
            },
            'required': ['document_id'],
        },
    },
]


class ToolError(Exception):
    """Bad input from the model: returned to it as an error result."""


def _int(args, name, required=True):
    value = args.get(name)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ToolError(f'{name} must be a whole number.')
    return int(value)


def _str(args, name, required=False):
    value = args.get(name)
    if value is None and not required:
        return ''
    if not isinstance(value, str):
        raise ToolError(f'{name} must be text.')
    return value.strip()


def _cut(text):
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f'\n[… cut at {MAX_CHARS} characters]'


def _date(text, name):
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ToolError(f'{name} must be a date like 2026-04-30.') from None


class Lookup:
    """Runs one turn's tool calls and remembers what was opened (the answer's sources)."""

    def __init__(self):
        self.opened = []        # [(kind, obj)] in order, no repeats
        self.steps = []         # what it did, for the page

    def _opened(self, kind, obj):
        if all((k, o.pk) != (kind, obj.pk) for k, o in self.opened):
            self.opened.append((kind, obj))

    def run(self, name, args):
        """(result text, is_error) for one tool call."""
        if not isinstance(args, dict):
            return 'The tool input wasn\'t a JSON object.', True
        handler = getattr(self, f'_{name}', None)
        if handler is None or name not in {t['name'] for t in TOOLS}:
            return f'There is no tool called {name}.', True
        try:
            return _cut(handler(args)), False
        except ToolError as e:
            return str(e), True

    def _search(self, args):
        query = _str(args, 'query', required=True)
        kind = _str(args, 'kind') or 'any'
        if kind not in ('any', REPORT, SETUP, DOCUMENT):
            raise ToolError('kind must be any, report, setup or document.')
        limit = min(max(_int(args, 'limit', required=False) or 8, 1), 20)
        self.steps.append(f'Searched {"" if kind == "any" else kind + "s "}for “{query}”')
        hits = index.search(query, None if kind == 'any' else kind, limit)
        if not hits:
            return f'No matches for "{query}". Try other or fewer words.'
        lines = []
        for hit in hits:
            ref = f"{hit['kind']} #{hit['id']}" + (f", page {hit['page']}" if hit['page'] else '')
            lines.append(f"- [{ref}] {hit['title']}\n  {hit['snippet']}")
        return f'{len(hits)} matches for "{query}":\n' + '\n'.join(lines)

    def _list_reports(self, args):
        reports = Report.objects.all()
        text = _str(args, 'text')
        for word in text.split():
            reports = reports.filter(Q(client__icontains=word) | Q(location__icontains=word)
                                     | Q(equipment_id__icontains=word) | Q(item_description__icontains=word)
                                     | Q(document_filename__icontains=word) | Q(document_title__icontains=word))
        report_type = _str(args, 'report_type')
        if report_type:
            from reports.report_types import report_type_choices
            keys = [k for k, label in report_type_choices() if report_type.lower() in (k.lower(), str(label).lower())]
            reports = reports.filter(report_type__in=keys or [report_type])
        start, end = _date(_str(args, 'date_from'), 'date_from'), _date(_str(args, 'date_to'), 'date_to')
        if start:
            reports = reports.filter(test_date__gte=start)
        if end:
            reports = reports.filter(test_date__lte=end)
        limit = min(max(_int(args, 'limit', required=False) or 25, 1), 50)
        total = reports.count()
        self.steps.append(f'Listed reports{": " + text if text else ""} ({total})')
        lines = []
        for r in reports.order_by('-test_date', '-pk')[:limit]:
            details = [f'test date {r.test_date}' if r.test_date else '', r.client, r.location,
                       f'equipment {r.equipment_id}' if r.equipment_id else '', r.item_description]
            lines.append(f"- [report #{r.pk}] {sources.report_label(r)}: " + ', '.join(d for d in details if d))
        return f'{total} reports' + (f' (first {limit})' if total > limit else '') + ':\n' + '\n'.join(lines)

    def _open_report(self, args):
        report = sources.get(REPORT, _int(args, 'report_id'))
        if report is None:
            raise ToolError('There is no report with that id.')
        self._opened(REPORT, report)
        self.steps.append(f'Opened {sources.report_label(report)}')
        return sources.report_text(report)

    def _open_setup(self, args):
        setup = sources.get(SETUP, _int(args, 'setup_id'))
        if setup is None:
            raise ToolError('There is no setup with that id.')
        self._opened(SETUP, setup)
        self.steps.append(f'Opened {sources.setup_label(setup)}')
        return sources.setup_text(setup)

    def _read_document(self, args):
        document = sources.get(DOCUMENT, _int(args, 'document_id'))
        if document is None:
            raise ToolError('There is no document with that id.')
        pages = sources.pdf_pages(document)
        first = _int(args, 'first_page', required=False) or 1
        last = _int(args, 'last_page', required=False) or min(first + 2, len(pages) or 1)
        if last < first:
            raise ToolError('last_page must be at or after first_page.')
        last = min(last, first + MAX_PAGES - 1)
        self._opened(DOCUMENT, document)
        header = sources.document_header(document)
        if not pages:
            return header + '\n(No readable text: not a PDF, or a scanned one.)'
        self.steps.append(f'Read {document.title}, pages {first}–{min(last, len(pages))}')
        chunks = [f'--- Page {n} of {len(pages)} ---\n{pages[n - 1]}' for n in range(first, min(last, len(pages)) + 1)]
        return header + f'\nPages: {len(pages)}\n' + '\n'.join(chunks)

    def links(self):
        return [sources.link(kind, obj) for kind, obj in self.opened]
