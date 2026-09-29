from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches
from copy import deepcopy
import os


class WordTemplateProcessor:
    """
    Word Template Processor is used as a find and replace for the selected word document.
    It will search for placeholder matches throughout the document, including tables, and
    replace them with the provided replacement text.
    """

    def __init__(self, template_path, output_path):
        self.template_path = template_path
        self.output_path = output_path
        self.document = Document(template_path)

    def replace(self, placeholder, replacement):
        for paragraph in self.document.paragraphs:
            self.replace_text_in_paragraphs(paragraph, placeholder, replacement)
        self.replace_in_table_cells_split_runs(placeholder, replacement)

    def replace_text_in_paragraphs(self, paragraph, placeholder, replacement):
        full_text = "".join(run.text for run in paragraph.runs)
        if placeholder in full_text:
            new_text = full_text.replace(placeholder, replacement)
            for run in paragraph.runs:
                run.text = ""
            if paragraph.runs:
                paragraph.runs[0].text = new_text
                print(f'Replaced {placeholder} with {replacement}')

    def replace_in_table_cells_split_runs(self, placeholder, replacement):
        for table in self.document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        full_text = "".join(run.text for run in paragraph.runs)
                        if placeholder in full_text:
                            new_text = full_text.replace(placeholder, replacement)
                            print(f'Replaced {replacement}')
                            for run in paragraph.runs:
                                run.text = ""
                            paragraph.runs[0].text = new_text

    # ── Multiple setup tables ──────────────────────────────────────────────

    def populate_setup_tables(self, setups):
        """
        Find the table marked with {{SETUP_TABLE}} in the document, duplicate it
        once per setup, and populate each copy with the corresponding Setup's fields.

        The template must contain exactly one table with a cell containing {{SETUP_TABLE}}.
        """
        template_table = self._find_table_with_placeholder('{{SETUP_TABLE}}')
        if template_table is None or not setups:
            return

        parent = template_table._tbl.getparent()
        insert_idx = list(parent).index(template_table._tbl)

        # Remove original from document body; we'll re-add populated copies
        parent.remove(template_table._tbl)

        setup_excluded = {'id', 'report', 'order'}

        for i, setup in enumerate(setups):
            table_copy = deepcopy(template_table._tbl)
            parent.insert(insert_idx + i, table_copy)

            from docx.table import Table
            copied_table = Table(table_copy, self.document)

            # Replace {{SETUP_TABLE}} sentinel with setup number
            self._replace_in_single_table(copied_table, '{{SETUP_TABLE}}', f'Setup {i + 1}')

            for field in setup._meta.concrete_fields:
                if field.name in setup_excluded:
                    continue
                value = getattr(setup, field.name, '') or ''
                placeholder = f'{{{{{field.name.upper()}}}}}'
                self._replace_in_single_table(copied_table, placeholder, str(value))

    def _find_table_with_placeholder(self, placeholder):
        for table in self.document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if placeholder in "".join(r.text for r in para.runs):
                            return table
        return None

    def _replace_in_single_table(self, table, placeholder, replacement):
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    full_text = "".join(r.text for r in para.runs)
                    if placeholder in full_text:
                        new_text = full_text.replace(placeholder, replacement)
                        for r in para.runs:
                            r.text = ""
                        if para.runs:
                            para.runs[0].text = new_text

    # ── Image boxes ────────────────────────────────────────────────────────

    def insert_images(self, report_images, width_inches=5.0):
        """
        Replace {{IMAGE_BLOCK}} paragraph(s) in the document with the provided images.

        Each ReportImage is inserted at the {{IMAGE_BLOCK}} sentinel paragraph
        (the first one found). If there are more images than sentinels, they are
        appended after the last inserted image paragraph.
        """
        sentinel = '{{IMAGE_BLOCK}}'

        for report_image in report_images:
            para = self._find_paragraph_with_placeholder(sentinel)
            if para is None:
                break
            para_elem = para._p

            # Clear sentinel text
            for run in para.runs:
                run.text = ''

            # Add image run to the paragraph
            run = para.add_run()
            try:
                run.add_picture(report_image.image.path, width=Inches(width_inches))
            except Exception:
                run.text = f'[Image: {report_image.caption or report_image.image.name}]'

            if report_image.caption:
                cap_para = self.document.add_paragraph(report_image.caption)
                cap_para._p.getparent().remove(cap_para._p)
                para_elem.addnext(cap_para._p)

    def _find_paragraph_with_placeholder(self, placeholder):
        for para in self.document.paragraphs:
            if placeholder in "".join(r.text for r in para.runs):
                return para
        return None

    # ── Results table ──────────────────────────────────────────────────────

    def populate_results_table(self, results_table):
        """
        Find the table with a {{RESULTS_TABLE}} sentinel in the document, set its
        header row from results_table.columns, and add one row per ResultsRow.

        Template table structure expected:
          Row 0: header cells (will be overwritten with column names)
          Row 1: placeholder body row containing {{RESULT_ROW}} (will be replaced)
        """
        if results_table is None:
            return

        table = self._find_table_with_placeholder('{{RESULTS_TABLE}}')
        if table is None:
            return

        columns = results_table.columns
        rows = list(results_table.rows.all())

        if not columns:
            return

        tbl_elem = table._tbl

        # ── Write header row ──────────────────────────────────────────────
        if table.rows:
            header_row = table.rows[0]
            for ci, col_name in enumerate(columns):
                if ci < len(header_row.cells):
                    self._set_cell_text(header_row.cells[ci], col_name)
                else:
                    # Add cell to header row if needed
                    self._add_cell_to_row(header_row, col_name)

        # ── Remove placeholder body row ───────────────────────────────────
        if len(table.rows) > 1:
            placeholder_row = table.rows[1]
            tbl_elem.remove(placeholder_row._tr)

        # ── Insert data rows ──────────────────────────────────────────────
        for result_row in rows:
            cells = result_row.cells or []
            tr = self._build_table_row(table, cells, columns)
            tbl_elem.append(tr)

    def _set_cell_text(self, cell, text):
        for para in cell.paragraphs:
            for run in para.runs:
                run.text = ''
        if cell.paragraphs and cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].text = text
        elif cell.paragraphs:
            cell.paragraphs[0].add_run(text)
        else:
            cell.add_paragraph(text)

    def _build_table_row(self, table, cells, columns):
        from docx.oxml import OxmlElement
        tr = OxmlElement('w:tr')
        for ci in range(len(columns)):
            tc = OxmlElement('w:tc')
            p = OxmlElement('w:p')
            r = OxmlElement('w:r')
            t = OxmlElement('w:t')
            t.text = cells[ci] if ci < len(cells) else ''
            r.append(t)
            p.append(r)
            tc.append(p)
            tr.append(tc)
        return tr

    def _add_cell_to_row(self, row, text):
        from docx.oxml import OxmlElement
        tc = OxmlElement('w:tc')
        p = OxmlElement('w:p')
        r = OxmlElement('w:r')
        t = OxmlElement('w:t')
        t.text = text
        r.append(t)
        p.append(r)
        tc.append(p)
        row._tr.append(tc)

    def save(self):
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self.document.save(self.output_path)
