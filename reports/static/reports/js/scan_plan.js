// Scan plan page: redraws the preview from the form's current values (debounced) and fills
// fields from a saved setup, or from the sensitivity block / wedge when one is picked.
// The probe / wedge lists and their filter boxes are catalogue_select.js.

const preview = document.getElementById('scan-plan-preview');

// Fill values come in inches (in/µs); a metric plan shows mm (m/s)
function planValue(name, value) {
    const units = form.elements.units;
    if (!units || units.value !== 'metric' || value === null || value === '') return value;
    const groups = JSON.parse(units.dataset.unitToggle || '{}');
    if ((groups.length || []).includes(name)) return (value * window.Units.MM_PER_IN).toFixed(2);
    if ((groups.velocity || []).includes(name)) return (value * window.Units.MM_PER_IN * 1000).toFixed(0);
    return value;
}
const form = preview.closest('form');
const status = document.getElementById('scan-plan-status');
const sideTwo = preview.querySelector('[data-side-2]');
let timer = null;

function formParams() {
    const params = new URLSearchParams(new FormData(form));
    params.delete('csrfmiddlewaretoken');
    return params;
}

async function redraw() {
    const params = formParams();
    sideTwo.hidden = params.get('sides') !== 'both';
    for (const img of preview.querySelectorAll('img[data-side]')) {
        if (img.closest('[hidden]')) continue;
        params.set('side', img.dataset.side);
        const response = await fetch(`${preview.dataset.url}?${params}`, { cache: 'no-store' });
        if (!response.ok) {
            // Keep the last good drawing while a value is incomplete
            status.textContent = 'Fill in the required values to update the drawing.';
            status.hidden = false;
            return;
        }
        const url = URL.createObjectURL(await response.blob());
        img.onload = () => URL.revokeObjectURL(url);
        img.src = url;
    }
    status.hidden = true;
}

function scheduleRedraw() {
    clearTimeout(timer);
    timer = setTimeout(redraw, 300);
}

form.addEventListener('input', scheduleRedraw);
form.addEventListener('change', scheduleRedraw);
redraw();

const fillSelect = document.getElementById('fill-from-setup');
if (fillSelect) {
    const fillValues = JSON.parse(document.getElementById('setup-fill-values').textContent);
    fillSelect.addEventListener('change', async () => {
        const item = fillValues[fillSelect.value];
        if (!item) return;
        fillSelect.value = '';
        const { probe_model: probe, wedge_model: wedge, ...fields } = item.fields;
        for (const [name, value] of Object.entries(fields)) {
            const input = form.elements[name];
            if (input) input.value = planValue(name, value);
        }
        // Pick the probe and wedge first: picking a wedge resets the wedge geometry fields...
        if (probe) await window.CatalogueSelect.setPair(form.elements.probe_model, probe, wedge);
        // ...then put back the geometry the setup's .nde recorded (hidden fields, mm / m/s)
        for (const [name, value] of Object.entries(item.wedge_geometry || {})) {
            const input = form.elements[name];
            if (input) input.value = value;
        }
        form.dispatchEvent(new Event('input'));
    });
}

// Picking a sensitivity block or wedge fills the values it carries
const catalogueValues = JSON.parse(document.getElementById('catalogue-fill-values').textContent);
for (const [name, byPk] of Object.entries(catalogueValues)) {
    const select = form.elements[name];
    if (!select) continue;
    select.addEventListener('change', () => {
        for (const [field, value] of Object.entries(byPk[select.value] || {})) {
            const input = form.elements[field];
            if (input && value !== null) input.value = planValue(field, value);
        }
        scheduleRedraw();
    });
}
