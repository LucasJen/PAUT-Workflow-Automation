from django.shortcuts import render
from django.conf import settings
from .services import document_processor
import os

def home(request):
    if request.method == 'POST':
        technician_name = request.POST.get('technician_name')
        
        print("FORM SUBMITTED!")
        print(f"Technician Name: {technician_name}")
        
        # Define paths
        template_path = os.path.join(settings.BASE_DIR, 'word_templates', 'long_form_template.docx')
        output_path = os.path.join(settings.BASE_DIR, 'outputs', 'report_output.docx')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Open and modify document
        doc = Document(template_path)
        replace_in_document(doc, '{{TECHNICIAN_NAME}}', technician_name)
        
        # Save
        doc.save(output_path)
        print(f"Saved output to: {output_path}")
        
    return render(request, 'reports/home.html')