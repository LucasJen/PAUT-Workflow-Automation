from django.shortcuts import render
from django.http import HttpResponse

def home(request):

    if request.method == 'POST':
        # Extract the technician name from the form
        technician_name = request.POST.get('technician_name')
        
        # Print to terminal (console)
        print("=" * 50)
        print("FORM SUBMITTED!")
        print(f"Technician Name: {technician_name}")
        print("=" * 50)

    return render(request, 'reports/home.html')