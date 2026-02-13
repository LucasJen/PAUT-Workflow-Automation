// These functions serve to create and manage data presets from the user inputted information

document.querySelectorAll('input, textarea').forEach(function(input) {
    input.addEventListener('input', saveFormData);
});

window.addEventListener('load', loadFormData);
    function savePreset() {
    
    let presetName = document.getElementById('preset-name').value.trim();

    if (!presetName) {
        alert('Please enter a preset name');
        return;
    }
    
    let formData = {};
    let inputs = document.querySelectorAll('input, textarea');
    
    inputs.forEach(function(input) {
        if (input.id !== 'preset-name') {
            formData[input.name] = input.value;
        }
    });
    
    formData['setupCount'] = setupCount;
    
    let presets = JSON.parse(localStorage.getItem('presets') || '{}');
    presets[presetName] = formData;
    localStorage.setItem('presets', JSON.stringify(presets));
    
    document.getElementById('preset-name').value = '';
    updatePresetDropdown();
    alert('Preset "' + presetName + '" saved successfully');
}

function loadPreset() {
    let presetName = document.getElementById('preset-select').value;
    if (!presetName) {
        alert('Please select a preset');
        return;
    }
    
    let presets = JSON.parse(localStorage.getItem('presets') || '{}');
    let formData = presets[presetName];
    
    if (!formData) {
        alert('Preset not found');
        return;
    }
    
    while (setupCount > 1) {
        document.getElementById('remove-setup-btn').click();
    }
    
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
    
    saveFormData();
    alert('Preset "' + presetName + '" loaded successfully');
}

function deletePreset() {
    let presetName = document.getElementById('preset-select').value;
    if (!presetName) {
        alert('Please select a preset to delete');
        return;
    }
    
    if (!confirm('Delete preset "' + presetName + '"?')) {
        return;
    }
    
    let presets = JSON.parse(localStorage.getItem('presets') || '{}');
    delete presets[presetName];
    localStorage.setItem('presets', JSON.stringify(presets));
    
    updatePresetDropdown();
    alert('Preset "' + presetName + '" deleted');
}

function updatePresetDropdown() {
    let presets = JSON.parse(localStorage.getItem('presets') || '{}');
    let select = document.getElementById('preset-select');
    
    select.innerHTML = '<option value="">Select a preset...</option>';
    
    Object.keys(presets).sort().forEach(function(name) {
        let option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
}

window.addEventListener('load', function() {
    loadFormData();
    updatePresetDropdown();
});