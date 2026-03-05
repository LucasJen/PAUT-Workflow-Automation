from django.shortcuts import render
from django.conf import settings
from .services.document_processor import WordTemplateProcessor
from .services.document_config import DOCUMENT_CONFIGS
import os

def home(request):
    if request.method == 'POST':
        report_type = "long_form"
        config = DOCUMENT_CONFIGS[report_type]

        template_path = os.path.join(
            settings.BASE_DIR, 'word_templates', 'long_form_template.docx'
        )

        output_path = os.path.join(
            settings.BASE_DIR, 'outputs', 'report_output.docx'
        )

        replacements = {
            f"{{{{{field.upper()}}}}}": request.POST.get(field)
            for field in config["LONG_FORM_FIELDS"]
        }

        print(replacements)
        num_setups = int(request.POST.get("num_setups"))
        print(f'{num_setups} setups')
        # List of all user inputs to be replaced: 


        technician_name = request.POST.get('technician_name')
       


        

        # # Open and modify document

        processor = WordTemplateProcessor(template_path, output_path)
        print('object created')

        processor.replace("{{TECHNICIAN_NAME}}", technician_name)

        processor.save()

        
    return render(request, 'reports/home.html')


def presets(request):
    return render(request, 'reports/presets.html')