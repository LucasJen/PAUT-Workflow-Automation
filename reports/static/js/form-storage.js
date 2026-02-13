//enables local storage in the even the webpage is refreshed. 

const formId = 'paut-report-form';

function saveFormData() {
    let formData = {};
    let form = document.querySelector('form');
    let inputs = form.querySelectorAll('input, textarea');
    
    inputs.forEach(function(input) {
        formData[input.name] = input.value;
    });
    
    formData['setupCount'] = setupCount;
    localStorage.setItem(formId, JSON.stringify(formData));
}

function loadFormData() {
    let savedData = localStorage.getItem(formId);
    if (!savedData) return;
    
    let formData = JSON.parse(savedData);
    
    if (formData.setupCount && formData.setupCount > 1) {
        for (let i = 2; i <= formData.setupCount; i++) {
            document.getElementById('add-setup-btn').click();
        }
    }
    
    let inputs = document.querySelectorAll('input, textarea');
    inputs.forEach(function(input) {
        if (formData[input.name]) {
            input.value = formData[input.name];
        }
    });
}

function clearFormData() {
    localStorage.removeItem(formId);
    let inputs = document.querySelectorAll('input, textarea');
    inputs.forEach(function(input) {
        input.value = '';
    });
    location.reload();
}



            


