"""
The assistant's search index: SQLite's built-in full-text search (FTS5) over every report, setup and
library document (a PDF page by page), ranked by relevance (BM25). Kept up to date by sync(), which
re-indexes only what changed since last time (IndexedItem keeps each item's stamp, a cheap sign
of change, and fingerprint, of its text), so it runs before every question at little cost.

The table (assistant_search) is created by migration 0001.
"""
import hashlib
import re

from django.db import connection, transaction
from django.db.models import Count, Max

from documents.models import Document
from reports.models import Report, ReportImage, ReportPerson, ResultsRow, Setup

from . import sources
from .models import IndexedItem
from .sources import DOCUMENT, REPORT, SETUP

TABLE = 'assistant_search'
WORD = re.compile(r"[\w][\w.\-/]*", re.UNICODE)


def _hash(*parts):
    return hashlib.sha256('\x1f'.join(str(p) for p in parts).encode('utf-8')).hexdigest()


def _rows_for(kind, obj):
    """[(page, title, body)] an item is indexed as (a document: its header, then one row per PDF page)."""
    if kind == REPORT:
        return [(0, sources.report_label(obj), sources.report_text(obj))]
    if kind == SETUP:
        return [(0, sources.setup_label(obj), sources.setup_text(obj))]
    label = sources.document_label(obj)
    rows = [(0, label, sources.document_header(obj))]
    rows += [(n, label, text) for n, text in enumerate(sources.pdf_pages(obj), start=1) if text]
    return rows


def _fingerprint(kind, obj):
    if kind == DOCUMENT:   # the PDF is only read again when the file or its details change
        return _hash(sources.document_signature(obj), obj.title, obj.description, obj.notes, obj.category)
    return _hash(sources.report_text(obj) if kind == REPORT else sources.setup_text(obj))


def _grouped(queryset, key):
    """{report id: (count, highest pk)} of a report's people, images or results rows, in one query."""
    return {row[key]: (row['n'], row['top']) for row in queryset.values(key).annotate(n=Count('pk'), top=Max('pk'))}


def _stamps():
    """
    {(kind, id): stamp}: a cheap sign of change, read in a few queries whatever the number of items.
    An item whose stamp is as last time isn't read again; one whose stamp changed has its text
    made and compared by fingerprint. A report's stamp is its last save, its setups' values and
    its people, images and results rows (replaced on every save); a setup's, its values.
    """
    setups, by_report = {}, {}
    for values in Setup.objects.values():
        stamp = _hash(*sorted(values.items()))
        setups[(SETUP, values['id'])] = stamp
        if values['report_id']:
            by_report.setdefault(values['report_id'], []).append(stamp)
    people = _grouped(ReportPerson.objects.all(), 'report_id')
    images = _grouped(ReportImage.objects.all(), 'report_id')
    rows = _grouped(ResultsRow.objects.all(), 'table__report_id')
    stamps = {(REPORT, pk): _hash(updated, sorted(by_report.get(pk, [])), people.get(pk), images.get(pk), rows.get(pk))
              for pk, updated in Report.objects.values_list('pk', 'updated_at')}
    stamps.update(setups)
    stamps.update({(DOCUMENT, d.pk): _fingerprint(DOCUMENT, d) for d in Document.objects.all()})
    return stamps


def _objects(kind, ids):
    """The items of `kind` whose stamp changed (reports with what their text needs)."""
    if kind == REPORT:
        return Report.objects.filter(pk__in=ids).prefetch_related('people', 'setups', 'images')
    return (Setup if kind == SETUP else Document).objects.filter(pk__in=ids)


def sync():
    """Re-indexes what changed and drops what was deleted. Returns how many items it (re)indexed."""
    known = {(i.kind, i.object_id): i for i in IndexedItem.objects.all()}
    stamps = _stamps()
    changed = 0
    for kind in (REPORT, SETUP, DOCUMENT):
        ids = [object_id for (k, object_id), stamp in stamps.items()
               if k == kind and (known.get((k, object_id)) is None or known[(k, object_id)].stamp != stamp)]
        for chunk in (ids[i:i + 200] for i in range(0, len(ids), 200)):
            for obj in _objects(kind, chunk):
                key, stamp = (kind, obj.pk), stamps[(kind, obj.pk)]
                fingerprint = _fingerprint(kind, obj)
                item = known.get(key)
                if item is not None and item.fingerprint == fingerprint:
                    # Saved again without a change to what's indexed
                    IndexedItem.objects.filter(pk=item.pk).update(stamp=stamp)
                    continue
                _replace(kind, obj, fingerprint, stamp)
                changed += 1
    for kind, object_id in set(known) - set(stamps):
        _remove(kind, object_id)
        changed += 1
    return changed


@transaction.atomic
def _replace(kind, obj, fingerprint, stamp=''):
    _remove(kind, obj.pk)
    with connection.cursor() as cursor:
        cursor.executemany(f'INSERT INTO {TABLE} (kind, object_id, page, title, body) VALUES (%s, %s, %s, %s, %s)',
                           [(kind, obj.pk, page, title, body) for page, title, body in _rows_for(kind, obj)])
    IndexedItem.objects.update_or_create(kind=kind, object_id=obj.pk,
                                         defaults={'fingerprint': fingerprint, 'stamp': stamp})


def _remove(kind, object_id):
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {TABLE} WHERE kind = %s AND object_id = %s', [kind, object_id])
    IndexedItem.objects.filter(kind=kind, object_id=object_id).delete()


def rebuild():
    """Indexes everything from scratch (Preferences › Assistant › Rebuild index)."""
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {TABLE}')
    IndexedItem.objects.all().delete()
    return sync()


def stats():
    counts = {kind: IndexedItem.objects.filter(kind=kind).count() for kind in (REPORT, SETUP, DOCUMENT)}
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {TABLE} WHERE kind = %s AND page > 0", [DOCUMENT])
        counts['pages'] = cursor.fetchone()[0]
    return counts


def _match(words, joiner):
    # Each word quoted (so codes like 100-UT-001 or SA-516 aren't read as search syntax), prefix-matched
    return f' {joiner} '.join('"' + w.replace('"', '') + '"*' for w in words)


def search(query, kind=None, limit=8):
    """
    Best matches for `query`: [{'kind', 'id', 'page', 'title', 'snippet'}], all words first, any word
    when nothing has them all. `kind` limits it to reports, setups or documents.
    """
    words = WORD.findall(query or '')[:12]
    if not words:
        return []
    for joiner in ('AND', 'OR'):
        sql = (f"SELECT kind, object_id, page, title, snippet({TABLE}, 4, '[', ']', ' … ', 40) "
               f"FROM {TABLE} WHERE {TABLE} MATCH %s" + (' AND kind = %s' if kind else '')
               + f' ORDER BY bm25({TABLE}, 0, 0, 0, 4.0, 1.0) LIMIT %s')
        params = [_match(words, joiner)] + ([kind] if kind else []) + [limit]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        if rows or len(words) == 1:
            break
    return [{'kind': k, 'id': int(i), 'page': int(p), 'title': t, 'snippet': s} for k, i, p, t, s in rows]
