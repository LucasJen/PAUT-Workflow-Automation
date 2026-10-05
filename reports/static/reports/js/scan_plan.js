// Scan plan page: redraws the preview from the form's current values (debounced), shows how much
// of the weld + HAZ it covers, suggests an index offset, switches between simple and advanced
// inputs, and fills fields from a saved setup, or from the sensitivity block / wedge when one is picked.
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
const figures = document.getElementById('scan-plan-figures');
let timer = null;

// ── Simple / advanced inputs: simple hides the advanced fields (they keep their values) ──

const fieldsPanel = document.getElementById('scan-plan-fields');
for (const name of JSON.parse(document.getElementById('advanced-fields').textContent)) {
    form.querySelector(`[data-field="${name}"]`)?.classList.add('advanced-only');
}

function applyMode() {
    const mode = form.querySelector('input[name="mode"]:checked')?.value || 'simple';
    fieldsPanel.dataset.mode = mode;
    // A section with nothing left to show in simple mode goes, heading and all
    fieldsPanel.querySelectorAll('.cell-grid').forEach(grid => {
        const empty = mode === 'simple' && !grid.querySelector('[data-field]:not(.advanced-only)');
        grid.hidden = empty;
        const title = grid.previousElementSibling;
        if (title?.classList.contains('cell-grid-head')) title.hidden = empty;
    });
}
form.querySelectorAll('input[name="mode"]').forEach(radio => radio.addEventListener('change', applyMode));
applyMode();

// ── Probe positions: the index offset and an optional second one, each with 90 / 270 deg skews ──

const SECOND = ['index_offset_2', 'skews_2'];   // the cells of the second offset's row
const secondButton = document.getElementById('toggle-second-offset');

function secondShown() {
    return !form.querySelector('[data-field="index_offset_2"]').hidden;
}

function showSecond(show) {
    SECOND.forEach(name => { form.querySelector(`[data-field="${name}"]`).hidden = !show; });
    if (!show) {  // removing the second position clears it
        form.elements.index_offset_2.value = '';
        form.elements.skew_90_2.checked = form.elements.skew_270_2.checked = false;
    }
    secondButton.innerHTML = show
        ? '<i class="bi bi-dash-lg"></i> Remove the second index offset'
        : '<i class="bi bi-plus-lg"></i> Add a second index offset';
}

secondButton.addEventListener('click', () => {
    const show = !secondShown();
    showSecond(show);
    if (show) form.elements.skew_90_2.checked = true;
    scheduleRedraw();
});
showSecond(Boolean(form.elements.index_offset_2.value) || form.elements.skew_90_2.checked
           || form.elements.skew_270_2.checked);

function drawings() {
    // [{position, side}] for each ticked skew: side 1 = 90 deg, side 2 = 270 deg
    const out = [];
    const boxes = [[1, 'skew_90', 'skew_270']];
    if (secondShown()) boxes.push([2, 'skew_90_2', 'skew_270_2']);
    for (const [position, ninety, twoSeventy] of boxes) {
        if (form.elements[ninety].checked) out.push({ position, side: 1 });
        if (form.elements[twoSeventy].checked) out.push({ position, side: 2 });
    }
    return out;
}

function figureFor(key, caption) {
    let figure = figures.querySelector(`[data-key="${key}"]`);
    if (!figure) {
        figure = document.createElement('figure');
        figure.className = 'scan-plan-figure';
        figure.dataset.key = key;
        figure.append(document.createElement('img'), document.createElement('figcaption'));
        figures.append(figure);
    }
    figure.querySelector('img').alt = `Scan plan, ${caption}`;
    figure.querySelector('figcaption').textContent = caption;
    return figure;
}

function formParams() {
    const params = new URLSearchParams(new FormData(form));
    params.delete('csrfmiddlewaretoken');
    return params;
}

async function redraw() {
    const params = formParams();
    const wanted = drawings();
    const keys = wanted.map(d => `${d.position}-${d.side}`);
    figures.querySelectorAll('figure').forEach(f => { if (!keys.includes(f.dataset.key)) f.remove(); });
    for (const { position, side } of wanted) {
        const offsetName = position === 1 ? 'index_offset' : 'index_offset_2';
        const offset = form.elements[offsetName].value;
        const where = position === 1 ? (offset ? `index offset ${offset}` : 'index offset at the weld toe')
                                     : `second index offset ${offset}`;
        const img = figureFor(`${position}-${side}`, `${side === 1 ? 90 : 270}° skew, ${where}`).querySelector('img');
        params.set('side', side);
        params.set('position', position);
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
    params.delete('position');
    showWedgeData(params);
}

// ── Wedge as drawn: the numbers the drawing uses, to check against the instrument ──

const wedgeData = document.getElementById('wedge-data');

async function showWedgeData(params) {
    params.delete('side');
    const response = await fetch(`${wedgeData.dataset.url}?${params}`, { cache: 'no-store' });
    if (!response.ok) return;
    const { wedge, coverage } = await response.json();
    showCoverage(coverage);
    if (!wedge) {
        wedgeData.replaceChildren(Object.assign(document.createElement('p'), {
            className: 'scan-plan-status', textContent: 'No probe or wedge picked: the wedge is a sketch.',
        }));
        return;
    }
    const metric = form.elements.units?.value === 'metric';
    const length = mm => metric ? `${mm.toFixed(2)} mm` : `${(mm / 25.4).toFixed(3)}"`;
    const rows = [
        ['Length × height', `${length(wedge.length)} × ${length(wedge.height)}`],
        ['Wedge angle', `${wedge.angle.toFixed(2)}°`],
        ['Wedge velocity', `${wedge.velocity.toFixed(0)} m/s`],
        ['First element: behind front', length(wedge.first_element_behind_front)],
        ['First element: height', length(wedge.first_element_height)],
        ['Face height at the back', length(wedge.heel_height)],
    ];
    const table = document.createElement('table');
    table.className = 'table table-sm wedge-data-table mb-0';
    table.createCaption().textContent = `Wedge as drawn (from the ${wedge.source})`;
    const body = table.createTBody();
    for (const [label, value] of rows) {
        const row = body.insertRow();
        row.insertCell().textContent = label;
        const cell = row.insertCell();
        cell.textContent = value;
        cell.className = 'mono';
    }
    wedgeData.replaceChildren(table);
}

// ── Coverage: how much of the weld + HAZ the ticked skews reach together ──

const coverageBox = document.getElementById('coverage-summary');

function lengthText(inches) {
    return form.elements.units?.value === 'metric' ? `${(inches * 25.4).toFixed(2)} mm` : `${inches.toFixed(3)}"`;
}

function percent(fraction) {
    // Never round a gap up to 100%
    const value = Math.floor(fraction * 1000) / 10;
    return `${value.toFixed(value === 100 ? 0 : 1)}%`;
}

function showCoverage(coverage) {
    if (!coverage) { coverageBox.hidden = true; return; }
    const parts = coverage.drawings.map(d => `${d.side === 1 ? 90 : 270}° skew${d.position === 2 ? ' (2nd offset)' : ''} `
                                             + `${percent(d.fraction)}`);
    coverageBox.className = `coverage-summary ${coverage.full ? 'is-full' : 'is-short'}`;
    coverageBox.replaceChildren(
        Object.assign(document.createElement('strong'), {
            textContent: coverage.full ? 'Weld + HAZ fully covered' : `Weld + HAZ ${percent(coverage.fraction)} covered`,
        }),
        Object.assign(document.createElement('span'), {
            textContent: ` (HAZ ${lengthText(coverage.haz_width)} each side; ${parts.join(', ') || 'no skew ticked'}).`
                         + (coverage.full ? '' : ' Gaps are shaded red in the drawing.'),
        }),
    );
    coverageBox.hidden = false;
}

// ── Suggest index offset: the offset (or pair) that covers the most of the weld + HAZ ──

const suggestButton = document.getElementById('suggest-offset');
const suggestStatus = document.getElementById('suggest-status');

function inputLength(inches) {
    // An inch value as the form shows it (mm for metric plans)
    return form.elements.units?.value === 'metric' ? (inches * 25.4).toFixed(2) : inches.toFixed(3);
}

suggestButton.addEventListener('click', async () => {
    suggestButton.disabled = true;
    suggestStatus.hidden = false;
    suggestStatus.textContent = 'Working out the offset…';
    try {
        const response = await fetch(`${suggestButton.dataset.url}?${formParams()}`, { cache: 'no-store' });
        if (!response.ok) {
            suggestStatus.textContent = 'Fill in the required values first.';
            return;
        }
        const s = await response.json();
        form.elements.index_offset.value = inputLength(s.offset);
        let text;
        if (s.second_offset !== null) {
            showSecond(true);
            form.elements.index_offset_2.value = inputLength(s.second_offset);
            form.elements.skew_90_2.checked = form.elements.skew_90.checked;
            form.elements.skew_270_2.checked = form.elements.skew_270.checked;
            text = `One offset reaches at most ${percent(s.fraction)}; two offsets, ${lengthText(s.offset)} and `
                 + `${lengthText(s.second_offset)}, reach ${percent(s.pair_fraction)}.`;
        } else if (s.low < s.high) {
            text = `Any offset from ${lengthText(s.low)} to ${lengthText(s.high)} covers ${percent(s.fraction)}; `
                 + `the middle, ${lengthText(s.offset)}, leaves the most room either way.`;
        } else {
            text = `${lengthText(s.offset)} covers the most: ${percent(s.fraction)}.`;
        }
        suggestStatus.textContent = `${text} Searched from the weld toe (${lengthText(s.toe)}) outwards.`;
        form.dispatchEvent(new Event('input'));
    } finally {
        suggestButton.disabled = false;
    }
});

function scheduleRedraw() {
    clearTimeout(timer);
    timer = setTimeout(redraw, 300);
}

form.addEventListener('input', scheduleRedraw);
form.addEventListener('change', scheduleRedraw);
redraw();

const fillSelect = document.getElementById('fill-from-setup');
if (fillSelect) {
    // Setups by pk, weld report group columns by 'g<pk>'
    const fillValues = {
        ...JSON.parse(document.getElementById('setup-fill-values').textContent),
        ...JSON.parse(document.getElementById('group-fill-values').textContent),
    };
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
