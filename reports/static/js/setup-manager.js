// These functions are used to create additional entries for PAUT setup information
// Two buttons are added in the report builder that allow an additional setup table to be created as well as deleted


let setupCount = 1;

document.getElementById('add-setup-btn').addEventListener('click', function() {
    if (setupCount >= 5) {
        alert('Maximum of 5 setups allowed');
        return;
    }
    
    setupCount++;
    
    let container = document.getElementById('setups-container');
    let firstSetup = document.querySelector('.setup-section');
    let newSetup = firstSetup.cloneNode(true);
    
    newSetup.setAttribute('data-setup-number', setupCount);
    newSetup.querySelector('h5').textContent = 'Setup ' + setupCount;
    
    let inputs = newSetup.querySelectorAll('input');
    inputs.forEach(function(input) {
        let baseName = input.name.replace(/_\d+$/, '');
        input.name = baseName + '_' + setupCount;
        input.value = '';
    });
    
    container.appendChild(newSetup);
});

document.getElementById('remove-setup-btn').addEventListener('click', function() {
    if (setupCount <= 1) {
        alert('Must have at least one setup');
        return;
    }
    
    let container = document.getElementById('setups-container');
    let allSetups = container.querySelectorAll('.setup-section');
    let lastSetup = allSetups[allSetups.length - 1];
    
    container.removeChild(lastSetup);
    setupCount--;
});