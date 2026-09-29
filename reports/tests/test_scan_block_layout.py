"""Photo-summary blocks: two per page (fixed block height), images fitted, comments sized to fit."""
import io
import re
import zipfile

from django.test import SimpleTestCase, TestCase
from docx import Document

from reports.models import Report, ReportImage, ResultsRow, ResultsTable, Setup
from reports.report_types import HIC_RESULTS_COLUMNS
from reports.services.report_render import (
    BLOCK_HEIGHT_IN, COMMENT_SIZES_PT, MAX_COMMENTS_IN, MIN_COMMENTS_IN, _comments_layout, render_report,
)
from reports.tests.test_phase2 import MediaMixin, png


class CommentsLayoutTests(SimpleTestCase):
    def test_short_comments_use_largest_font_and_minimum_height(self):
        self.assertEqual(_comments_layout('No indications.'), (COMMENT_SIZES_PT[0], MIN_COMMENTS_IN))

    def test_longer_comments_step_the_font_down_but_stay_in_the_box(self):
        sizes = []
        for n in (1, 5, 10, 15, 40):
            size, height = _comments_layout('Blister indications near the ID surface. ' * n)
            self.assertLessEqual(height, MAX_COMMENTS_IN)
            sizes.append(size)
        self.assertEqual(sizes, sorted(sizes, reverse=True))  # never grows as text gets longer
        self.assertEqual(sizes[-1], COMMENT_SIZES_PT[-1])


class BlockRenderTests(MediaMixin, TestCase):
    def test_blocks_have_fixed_height_and_fitted_images(self):
        report = Report.objects.create(document_filename='r')
        Setup.objects.create(report=report, title='HydroFORM')
        table = ResultsTable.objects.create(report=report, columns=[h for _, h in HIC_RESULTS_COLUMNS])
        for i, (comments, size_px) in enumerate([('Short.', (1400, 700)), ('Long comment. ' * 60, (500, 900))]):
            ResultsRow.objects.create(table=table, order=i, cells=[f'S{i}', '', '', '', '', '', comments])
            img = png(f's{i}.png', ('red', 'blue')[i])
            ReportImage.objects.create(report=report, kind=ReportImage.SCAN, scan_id=f'S{i}', image=img, order=i)
            # replace with an image of the wanted proportions
            from PIL import Image
            path = ReportImage.objects.get(scan_id=f'S{i}').image.path
            Image.new('RGB', size_px, 'green').save(path)

        content = render_report(report)
        xml = zipfile.ZipFile(io.BytesIO(content)).read('word/document.xml').decode()
        doc = Document(io.BytesIO(content))
        blocks = [t for t in doc.tables if len(t.rows) == 2 and t.rows[1].cells[-1].text.startswith('Comments')]
        self.assertEqual(len(blocks), 2)
        for block, (width_px, height_px) in zip(blocks, [(1400, 700), (500, 900)]):
            heights = []
            for row in block.rows:
                trpr = row._tr.trPr
                self.assertIsNotNone(trpr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cantSplit'))
                self.assertEqual(row.height_rule, 2)  # WD_ROW_HEIGHT_RULE.EXACTLY
                heights.append(row.height.inches)
            self.assertAlmostEqual(sum(heights), BLOCK_HEIGHT_IN, places=2)
            shape = block.rows[0].cells[0]._tc.xpath('.//wp:extent')[0]
            w_in, h_in = int(shape.get('cx')) / 914400, int(shape.get('cy')) / 914400
            self.assertAlmostEqual(w_in / h_in, width_px / height_px, places=2)  # proportions kept
            self.assertLessEqual(h_in, heights[0])  # fits in its row
        self.assertIsNone(re.search(r'\{\{|\{%', xml))
