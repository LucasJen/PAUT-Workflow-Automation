from django.shortcuts import render
from django.conf import settings
from .services.document_processor import WordTemplateProcessor
import os

def home(request):
    if request.method == 'POST':
        technician_name = request.POST.get('technician_name')
        
        # print("FORM SUBMITTED!")
        # print(f"Technician Name: {technician_name}")
        
        # Define paths for the input document and output location.

        #input template
        template_path = os.path.join(
            settings.BASE_DIR, 'word_templates', 'long_form_template.docx'
        )
        print(template_path)
        # output product
        output_path = os.path.join(
            settings.BASE_DIR, 'outputs', 'report_output.docx'
        )
        print(output_path)
        
        # Open and modify document
        processor = WordTemplateProcessor(template_path, output_path)
        print('object created')
        processor.replace("{{TECHNICIAN_NAME}}", technician_name)
        print('replacer ran')
        #save changes to output location
        processor.save()
        print('document saved')

        
    return render(request, 'reports/home.html')