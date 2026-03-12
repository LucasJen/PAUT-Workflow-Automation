from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .services.document_processor import WordTemplateProcessor
import os
from .forms import ReportForm, SetupForm
from .models import Report, Setup


def home(request):
    return render(request, 'reports/home.html')

def create_report(request):
    if request.method == 'POST':
        form = ReportForm(request.POST)
        setup_form = SetupForm(request.POST)
        if form.is_valid() and setup_form.is_valid():
            form.save()
            setup_form.save()
    else:
        form = ReportForm()
        setup_form = SetupForm()
    return render(request, 'reports/create_report.html', {'form': form, 'setup_form': setup_form})
        
        
        # report_type = "long_form"
        # config = DOCUMENT_CONFIGS[report_type]

        # template_path = os.path.join(
        #     settings.BASE_DIR, 'word_templates', 'long_form_template.docx'
        # )
        # output_path = os.path.join(
        #     settings.BASE_DIR, 'outputs', 'report_output.docx'
        # )

        # replacements = {
        #     f"{{{{{field.upper()}}}}}": request.POST.get(field)
        #     for field in config["LONG_FORM_FIELDS"]
        # }

        # num_setups = int(request.POST.get("num_setups"))
        # # List of all user inputs to be replaced: 

        # technician_name = request.POST.get('technician_name')
    
        # # Open and modify document
        # processor = WordTemplateProcessor(template_path, output_path)
        # processor.replace("{{TECHNICIAN_NAME}}", technician_name)
        # processor.save()

        
    # return render(request, 'reports/home.html')

def setup_list(request):
    setups = Setup.objects.all()
    return render(request, 'reports/setup_list.html', {'setups': setups})

def edit_setups(request):
    setup = get_object_or_404(Setup, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            setup.delete()
            return redirect('report-list')
        form = SetupForm(request.POST, instance=setup)
        if form.is_valid():
            form.save()
            return redirect('report-list')
    else:
        form = SetupForm(instance=setup)
    return render(request, 'reports/edit_setups.html', {'form': form, 'setup': setup})

def report_list(request):
    reports = Report.objects.all()
    return render(request, 'reports/report_list.html', {'reports': reports})