"""
A small read-only .xlsx reader (the standard library's zipfile and lxml, no Excel): each sheet's
cell values as Excel last saved them - text as typed, numbers as their number format shows them
(0.28 in a 0.000 cell reads '0.280'), dates, and formulas' cached results - keyed by cell
reference ('C7'), and the pictures placed on a sheet with where they sit.
"""
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta

from lxml import etree

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
R_ID = f'{{{NS["r"]}}}id'
R_EMBED = f'{{{NS["r"]}}}embed'
_REF = re.compile(r'([A-Z]+)(\d+)')
# Built-in number formats (ECMA-376 18.8.30) that matter here
_BUILTIN_FORMATS = {1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00', 9: '0%', 10: '0.00%', 11: '0.00E+00', 49: '@'}
_DATE_FORMAT_IDS = set(range(14, 23)) | set(range(45, 48)) | {27, 30, 36, 50, 57}
EMU_PER_PIXEL = 9525


class XlsxError(Exception):
    """The file isn't a workbook this reader can open."""


def split_ref(ref):
    """'AB12' -> ('AB', 12)."""
    match = _REF.fullmatch(ref)
    if not match:
        raise ValueError(ref)
    return match.group(1), int(match.group(2))


def column_number(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def column_letters(n):
    out = ''
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def reading_order(ref):
    col, row = split_ref(ref)
    return row, column_number(col)


@dataclass
class Picture:
    """A picture on a sheet: its bytes, file extension and where it sits (pixels from the sheet's
    top-left; row / col are the 1-based cell its top-left corner is in)."""
    data: bytes
    ext: str
    row: int
    col: int
    left: float
    top: float
    width: float
    height: float


class Sheet:
    def __init__(self, name, cells, merged, hidden=False, pictures=None):
        self.name = name
        self.cells = cells              # 'C7' -> str / float / datetime (numbers formatted: see text())
        self.merged = merged            # [(top-left ref, bottom-right ref)]
        self.hidden = hidden
        self.pictures = pictures or []  # [Picture]
        self.shown = {}                 # 'C7' -> the number as its format shows it

    def get(self, ref, default=''):
        return self.cells.get(ref, default)

    def text(self, ref):
        """The cell as text, the way it reads on the page."""
        if ref in self.shown:
            return self.shown[ref]
        return as_text(self.cells.get(ref, ''))

    def find(self, pattern, flags=re.I):
        """Refs of the cells whose text matches `pattern`, in reading order."""
        rx = re.compile(pattern, flags)
        found = [ref for ref, v in self.cells.items() if isinstance(v, str) and rx.search(v)]
        return sorted(found, key=reading_order)


def as_text(value):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%m/%d/%Y') if not (value.hour or value.minute) else value.strftime('%m/%d/%Y %H:%M')
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(round(value, 10)).rstrip('0').rstrip('.')
    return str(value).strip()


def excel_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=float(serial))


def _tokens(section):
    """A number format section as [(kind, text)]: 'lit' text shown as is, 'num' digit placeholders."""
    out, i = [], 0
    while i < len(section):
        ch = section[i]
        if ch == '"':
            close = section.find('"', i + 1)
            close = len(section) if close < 0 else close
            out.append(('lit', section[i + 1:close]))
            i = close + 1
        elif ch == '\\' and i + 1 < len(section):
            out.append(('lit', section[i + 1]))
            i += 2
        elif ch == '[':
            close = section.find(']', i)
            i = len(section) if close < 0 else close + 1
        elif ch in '_*':
            i += 2   # padding to a character's width, repeated fill
        elif ch in '0#?.,':
            out.append(('num', ch))
            i += 1
        elif ch == '%':
            out.append(('pct', ch))
            i += 1
        else:
            out.append(('lit', ch))
            i += 1
    return out


def format_number(value, code):
    """A number as a (simple) Excel number format shows it: decimals, zero padding, %, thousands, literal text."""
    if not code or code.lower() == 'general' or code == '@':
        return as_text(value)
    sections = code.split(';')
    section = sections[0]
    negative = value < 0 and len(sections) > 1
    if negative:
        section, value = sections[1], -value
    if re.search(r'E[+-]', section, re.I) or '/' in section:
        return as_text(value)
    tokens = _tokens(section)
    nums = [i for i, (kind, _) in enumerate(tokens) if kind == 'num']
    if not nums:
        return as_text(value)
    pattern = ''.join(text for kind, text in tokens[nums[0]:nums[-1] + 1] if kind == 'num')
    whole_part, _, frac_part = pattern.partition('.')
    percent = any(kind == 'pct' for kind, _ in tokens)
    number = value * 100 if percent else value
    decimals = len(frac_part)
    text = f'{number:,.{decimals}f}' if ',' in whole_part.strip(',') else f'{number:.{decimals}f}'
    digits = whole_part.count('0')   # 0000 pads 700 to 0700
    if digits > 1:
        sign, body = ('-', text[1:]) if text.startswith('-') else ('', text)
        whole, dot, frac = body.partition('.')
        text = sign + whole.zfill(digits) + dot + frac
    if '#' in frac_part or '?' in frac_part:   # optional decimals: 0.0## drops trailing zeros past the 0s
        keep = len(frac_part.rstrip('#?'))
        whole, _, frac = text.partition('.')
        frac = frac[:keep] + frac[keep:].rstrip('0')
        text = whole + ('.' + frac if frac else '')
    shown = lambda part: ''.join(t if kind == 'lit' else '%' if kind == 'pct' else '' for kind, t in part)
    return shown(tokens[:nums[0]]) + text + shown(tokens[nums[-1] + 1:])


def _parse(zf, name):
    with zf.open(name) as f:
        return etree.parse(f, etree.XMLParser(resolve_entities=False, huge_tree=True)).getroot()


def _rels(zf, part):
    """{rId: target part} of a part's relationships."""
    folder, _, name = part.rpartition('/')
    rels = f'{folder}/_rels/{name}.rels'
    if rels not in zf.namelist():
        return {}
    return {r.get('Id'): _target(part, r.get('Target')) for r in _parse(zf, rels).findall('rel:Relationship', NS)
            if r.get('TargetMode') != 'External'}


def _target(base, target):
    if target.startswith('/'):
        return target.lstrip('/')
    parts = (base.rsplit('/', 1)[0] + '/' + target).split('/')
    out = []
    for p in parts:
        if p == '..':
            if out:
                out.pop()
        elif p and p != '.':
            out.append(p)
    return '/'.join(out)


def _shared_strings(zf):
    if 'xl/sharedStrings.xml' not in zf.namelist():
        return []
    root = _parse(zf, 'xl/sharedStrings.xml')
    out = []
    for si in root.findall('m:si', NS):
        # Rich text runs, without the phonetic (rPh) hints
        out.append(''.join(t.text or '' for t in si.iter(f'{{{NS["m"]}}}t')
                           if t.getparent().tag != f'{{{NS["m"]}}}rPh'))
    return out


def _styles(zf):
    """[(format code, is a date)] per cell style (cellXfs index)."""
    if 'xl/styles.xml' not in zf.namelist():
        return []
    root = _parse(zf, 'xl/styles.xml')
    custom = {int(f.get('numFmtId')): f.get('formatCode', '') for f in root.findall('m:numFmts/m:numFmt', NS)}
    styles = []
    for xf in root.findall('m:cellXfs/m:xf', NS):
        fid = int(xf.get('numFmtId', 0))
        code = custom.get(fid, _BUILTIN_FORMATS.get(fid, 'General'))
        bare = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', '', code).lower()
        is_date = fid in _DATE_FORMAT_IDS or (fid in custom and bool(re.search(r'[dy]|h.*m|m.*s', bare)))
        styles.append((code, is_date))
    return styles


def read_workbook(path_or_file):
    """{sheet name: Sheet} in the workbook's order. Raises XlsxError."""
    try:
        zf = zipfile.ZipFile(path_or_file)
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise XlsxError('This is not an .xlsx workbook (an older .xls, or not an Excel file).') from e
    with zf:
        names = set(zf.namelist())
        if 'xl/workbook.xml' not in names:
            raise XlsxError('This file has no Excel workbook in it.')
        try:
            book = _parse(zf, 'xl/workbook.xml')
            targets = _rels(zf, 'xl/workbook.xml')
            strings = _shared_strings(zf)
            styles = _styles(zf)
            sheets = {}
            for node in book.findall('m:sheets/m:sheet', NS):
                target = targets.get(node.get(R_ID))
                if not target or target not in names:
                    continue
                hidden = node.get('state') in ('hidden', 'veryHidden')
                sheets[node.get('name')] = _read_sheet(zf, target, node.get('name'), strings, styles, hidden)
        except (etree.XMLSyntaxError, KeyError, ValueError, IndexError) as e:
            raise XlsxError(f'The workbook could not be read ({e}).') from e
        return sheets


def _read_sheet(zf, target, name, strings, styles, hidden):
    root = _parse(zf, target)
    cells, shown = {}, {}
    for c in root.iterfind('m:sheetData/m:row/m:c', NS):
        ref = c.get('r')
        if not ref:
            continue
        kind = c.get('t', 'n')
        v = c.find('m:v', NS)
        if kind == 'inlineStr':
            node = c.find('m:is', NS)
            value = ''.join(node.itertext()) if node is not None else ''
        elif v is None or v.text is None:
            continue
        elif kind == 's':
            index = int(v.text)
            value = strings[index] if index < len(strings) else ''
        elif kind == 'str':
            value = v.text
        elif kind == 'e':
            continue    # #N/A, #REF!...
        elif kind == 'b':
            value = 'TRUE' if v.text == '1' else 'FALSE'
        else:
            try:
                number = float(v.text)
            except ValueError:
                continue
            style = int(c.get('s', 0))
            code, is_date = styles[style] if style < len(styles) else ('General', False)
            if is_date:
                try:
                    value = excel_date(number)
                except OverflowError:
                    value = number
            else:
                value = number
                shown[ref] = format_number(number, code)
        if value == '' or value is None:
            continue
        cells[ref] = value
    merged = []
    for m in root.iterfind('m:mergeCells/m:mergeCell', NS):
        a, _, b = m.get('ref', '').partition(':')
        if a and b:
            merged.append((a, b))
    sheet = Sheet(name, cells, merged, hidden, _pictures(zf, target, root))
    sheet.shown = shown
    return sheet


# ── Pictures ──────────────────────────────────────────────────────────────

def _grid(root):
    """(column left edge in px, row top edge in px) functions from the sheet's widths and heights."""
    fmt = root.find('m:sheetFormatPr', NS)
    default_width = float(fmt.get('defaultColWidth') or (float(fmt.get('baseColWidth') or 8) + 0.71)) if fmt is not None else 8.43
    default_height = float(fmt.get('defaultRowHeight') or 15) if fmt is not None else 15.0
    widths = {}
    for col in root.iterfind('m:cols/m:col', NS):
        for n in range(int(col.get('min')), min(int(col.get('max')), 400) + 1):
            widths[n] = 0.0 if col.get('hidden') == '1' else float(col.get('width', default_width))
    heights = {}
    for row in root.iterfind('m:sheetData/m:row', NS):
        if row.get('ht') or row.get('hidden') == '1':
            heights[int(row.get('r'))] = 0.0 if row.get('hidden') == '1' else float(row.get('ht'))

    def px_width(chars):
        return int(chars * 7 + 5) if chars else 0

    def col_left(index0):   # 0-based column index
        return sum(px_width(widths.get(n, default_width)) for n in range(1, index0 + 1))

    def row_top(index0):
        return sum(heights.get(n, default_height) for n in range(1, index0 + 1)) * 96 / 72
    return col_left, row_top


def _pictures(zf, sheet_part, root):
    drawing = root.find('m:drawing', NS)
    if drawing is None:
        return []
    rels = _rels(zf, sheet_part)
    part = rels.get(drawing.get(R_ID))
    if not part or part not in zf.namelist():
        return []
    images = _rels(zf, part)
    col_left, row_top = _grid(root)
    out = []
    for anchor in _parse(zf, part):
        tag = etree.QName(anchor).localname
        if tag not in ('twoCellAnchor', 'oneCellAnchor', 'absoluteAnchor'):
            continue
        blip = anchor.find('.//a:blip', NS)
        if blip is None or anchor.find('xdr:pic', NS) is None and anchor.find('.//xdr:pic', NS) is None:
            continue
        image = images.get(blip.get(R_EMBED))
        if not image or image not in zf.namelist():
            continue

        def point(node):
            col = int(node.findtext('xdr:col', '0', NS))
            row = int(node.findtext('xdr:row', '0', NS))
            x = col_left(col) + int(node.findtext('xdr:colOff', '0', NS)) / EMU_PER_PIXEL
            y = row_top(row) + int(node.findtext('xdr:rowOff', '0', NS)) / EMU_PER_PIXEL
            return col, row, x, y

        if tag == 'absoluteAnchor':
            pos, ext = anchor.find('xdr:pos', NS), anchor.find('xdr:ext', NS)
            x, y = int(pos.get('x')) / EMU_PER_PIXEL, int(pos.get('y')) / EMU_PER_PIXEL
            w, h = int(ext.get('cx')) / EMU_PER_PIXEL, int(ext.get('cy')) / EMU_PER_PIXEL
            col = row = 0
        else:
            col, row, x, y = point(anchor.find('xdr:from', NS))
            if tag == 'twoCellAnchor':
                _, _, x2, y2 = point(anchor.find('xdr:to', NS))
                w, h = x2 - x, y2 - y
            else:
                ext = anchor.find('xdr:ext', NS)
                w, h = int(ext.get('cx')) / EMU_PER_PIXEL, int(ext.get('cy')) / EMU_PER_PIXEL
        out.append(Picture(zf.read(image), image.rsplit('.', 1)[-1].lower(), row + 1, col + 1, x, y, w, h))
    return out
