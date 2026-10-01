// Scan plan page: redraws the preview from the form's current values (debounced) and fills
// fields from a saved setup, or from the sensitivity block / wedge when one is picked.

const preview = document.getElementById('scan-plan-preview');
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
    fillSelect.addEventListener('change', () => {
        const item = fillValues[fillSelect.value];
        if (!item) return;
        for (const [name, value] of Object.entries(item.fields)) {
            const input = form.elements[name];
            if (input) input.value = value;
        }
        fillSelect.value = '';
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
            if (input && value !== null) input.value = value;
        }
        scheduleRedraw();
    });
}

// Only wedges that fit the selected probe can be picked: the list is fetched for each probe
// (the Beamtool library has thousands of probe-specific wedges)
const probeSelect = form.elements.probe_model;
const wedgeSelect = form.elements.wedge_model;

async function loadWedges() {
    if (!probeSelect.value) return;  // without a probe the page lists the general wedges
    const response = await fetch(`${preview.dataset.wedgesUrl}?probe=${probeSelect.value}`);
    if (!response.ok) return;
    const { wedges } = await response.json();
    const current = wedgeSelect.value;
    const blank = wedgeSelect.options[0];
    wedgeSelect.replaceChildren(blank, ...wedges.map(([pk, name]) => new Option(name, pk)));
    wedgeSelect.value = wedges.some(([pk]) => String(pk) === current) ? current : '';
    if (wedgeSelect.value !== current) scheduleRedraw();
}

if (probeSelect && wedgeSelect) {
    probeSelect.addEventListener('change', loadWedges);
}
