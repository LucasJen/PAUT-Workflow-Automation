"""
The equipment inventory as an Excel workbook (for audits): a sheet per library, one row per item,
a column per field. Written directly as Office Open XML (a zip of XML parts), so it needs nothing
beyond Python; dates are real Excel dates, the header row is bold and stays on screen.
"""
import io
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from .models import CalibrationBlock, Encoder, Probe, Scope, SensitivityBlock

EXCEL_EPOCH = date(1899, 12, 30)


def _sheets():
    """(sheet name, model, field names) per library, in the sidebar's order."""
    def fields(model, skip=()):
        return [f.name for f in model._meta.concrete_fields if f.name not in ('id', *skip)]
    return [
        ('Scopes', Scope, fields(Scope)),
        ('Probes', Probe, fields(Probe)),
        ('Calibration blocks', CalibrationBlock, fields(CalibrationBlock)),
        ('Sensitivity blocks', SensitivityBlock, fields(SensitivityBlock)),
        ('Encoders', Encoder, fields(Encoder)),
    ]


def _column(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref, value, header=False):
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        value = 'Yes' if value else 'No'
    if isinstance(value, date):
        return f'<c r="{ref}" s="2"><v>{(value - EXCEL_EPOCH).days}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    style = ' s="1"' if header else ''
    return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _value(obj, name):
    value = getattr(obj, name)
    field = obj._meta.get_field(name)
    if field.is_relation:
        return str(value) if value is not None else None
    return value


def _sheet_xml(model, names):
    labels = [(lambda v: v[:1].upper() + v[1:])(str(model._meta.get_field(n).verbose_name)) for n in names]
    rows = [''.join(_cell(f'{_column(i)}1', label, header=True) for i, label in enumerate(labels))]
    for r, obj in enumerate(model.objects.order_by('pk'), start=2):
        rows.append(''.join(_cell(f'{_column(i)}{r}', _value(obj, n)) for i, n in enumerate(names)))
    widths = ''.join(f'<col min="{i + 1}" max="{i + 1}" width="{max(12, min(40, len(label) + 4))}" customWidth="1"/>'
                     for i, label in enumerate(labels))
    data = ''.join(f'<row r="{r}">{cells}</row>' for r, cells in enumerate(rows, start=1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>'
            f'<cols>{widths}</cols><sheetData>{data}</sheetData></worksheet>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
          '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
          '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
          '</styleSheet>')


def inventory_workbook():
    """The .xlsx bytes."""
    sheets = _sheets()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + '</Types>')
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, (name, _, _) in enumerate(sheets, 1))
                   + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
                             f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/'
                     '2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', STYLES)
        for i, (_, model, names) in enumerate(sheets, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', _sheet_xml(model, names))
    return out.getvalue()
