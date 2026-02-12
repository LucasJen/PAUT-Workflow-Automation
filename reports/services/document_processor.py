from docx import Document
import os

class WordTemplateProcessor:
    def __init__(self, template_path, output_path):
        self.template_path = template_path
        self.output_path = output_path
        self.document = Document(template_path)

    def replace_text_in_paragraphs(self, paragraph, placeholder, replacement):
        if placeholder in paragraph.text:
            for run in paragraph.runs:
                if placeholder in run.text:
                    run.text = run.text.replace(placeholder, replacement)
                    print("reeeee")
    
    def replace(self, placeholder, replacement):

        # Search for matching placeholders with the text of the document.
        print("Searching Paragraphs")
        # Search Paragraphs
        for paragraph in self.document.paragraphs:
            self.replace_text_in_paragraphs(paragraph, placeholder, replacement)

        print("searching tables")
        # Search Tables
        for table in self.document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        self.replace_text_in_paragraphs(paragraph, placeholder, replacement)


    def save(self):
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        self.document.save(self.output_path)


