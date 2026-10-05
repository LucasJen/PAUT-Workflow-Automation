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

// ── Weld type: fields that only some weld types use show for those (they keep their values) ──

const weldType = form.elements.weld_type;
const weldTypeFields = JSON.parse(weldType.dataset.weldTypeFields || '{}');

function applyWeldType() {
    for (const [name, types] of Object.entries(weldTypeFields)) {
        form.querySelector(`[data-field="${name}"]`)?.classList.toggle('weld-type-hidden', !types.includes(weldType.value));
    }
}
weldType.addEventListener('change', applyWeldType);
applyWeldType();
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

function formParams() {
    const params = new URLSearchParams(new FormData(form));
    params.delete('csrfmiddlewaretoken');
    return params;
}

// ── Drawings: one interactive view (scan_plan_view.js) per ticked skew per index offset ──

const views = {};          // 'position-side' -> ScanPlanView
let latestRequest = 0;     // only the newest redraw's answer is drawn

function caption(meta) {
    const name = meta.position === 1 ? 'index_offset' : 'index_offset_2';
    const entered = form.elements[name].value;
    const where = meta.position === 1
        ? (entered ? `index offset ${lengthText(meta.index_offset)}` : `index offset at the weld toe (${lengthText(meta.index_offset)})`)
        : `second index offset ${lengthText(meta.index_offset)}`;
    return `${meta.side === 1 ? 90 : 270}° skew, ${where}`;
}

function viewFor(key) {
    if (!views[key]) {
        const figure = document.createElement('figure');
        figure.className = 'scan-plan-figure';
        figure.dataset.key = key;
        figure.append(document.createElement('figcaption'));
        views[key] = new window.ScanPlanView(figure, {
            format: lengthText,
            // The offset snaps to 0.01" (0.25 mm for metric plans)
            step: () => (form.elements.units?.value === 'metric' ? 0.25 / 25.4 : 0.01),
            onOffset: (position, inches) => {
                form.elements[position === 1 ? 'index_offset' : 'index_offset_2'].value = inputLength(inches);
                form.dispatchEvent(new Event('input'));
            },
        });
    }
    return views[key];
}

async function redraw() {
    const request = ++latestRequest;
    const response = await fetch(`${preview.dataset.scenesUrl}?${formParams()}`, { cache: 'no-store' });
    if (request !== latestRequest) return;
    if (!response.ok) {
        // Keep the last good drawing while a value is incomplete
        status.textContent = 'Fill in the required values to update the drawing.';
        status.hidden = false;
        return;
    }
    const data = await response.json();
    if (request !== latestRequest) return;
    const keys = data.drawings.map(scene => `${scene.meta.position}-${scene.meta.side}`);
    for (const key of Object.keys(views)) {
        if (!keys.includes(key)) {
            views[key].figure.remove();
            delete views[key];
        }
    }
    data.drawings.forEach((scene, i) => {
        const view = viewFor(keys[i]);
        const text = caption(scene.meta);
        view.figure.querySelector('figcaption').textContent = text;
        view.update(scene, data.colours, data.width_px, `Scan plan, ${text}`);
        figures.append(view.figure);   // in the server's order
    });
    status.hidden = true;
    showCoverage(data.coverage);
    showWedgeData(data.wedge);
}

document.getElementById('reset-views').addEventListener('click', () => Object.values(views).forEach(v => v.resetView()));

// Beam legs from the drawing's toolbar (the same value as the Beam legs field)
const legButtons = document.querySelectorAll('[data-legs]');
function showLegs() {
    legButtons.forEach(b => b.classList.toggle('active', b.dataset.legs === form.elements.legs.value));
}
legButtons.forEach(button => button.addEventListener('click', () => {
    form.elements.legs.value = button.dataset.legs;
    showLegs();
    form.dispatchEvent(new Event('change'));
}));
form.elements.legs.addEventListener('change', showLegs);
showLegs();

// ── Wedge as drawn: the numbers the drawing uses, to check against the instrument ──

const wedgeData = document.getElementById('wedge-data');

function showWedgeData(wedge) {
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
        const label = fillSelect.selectedOptions[0].textContent;
        fillSelect.value = '';
        const { probe_model: probe, wedge_model: wedge, ...fields } = item.fields;
        for (const [name, value] of Object.entries(fields)) {
            const input = form.elements[name];
            if (input) input.value = planValue(name, value);
        }
        if (!form.elements.name.value.trim() && item.name) form.elements.name.value = item.name;
        showFillStatus(label, item);
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

// What a fill from a setup / group changed, and what it couldn't (thickness needs a sensitivity block)
function showFillStatus(label, item) {
    const status = document.getElementById('fill-status');
    let thickness;
    if (item.block) thickness = `sensitivity block ${item.block} (thickness, pipe size, bevel, velocity)`;
    else if (item.has_report) thickness = 'its report has no sensitivity block, so the thickness is unchanged';
    else thickness = 'a saved setup has no sensitivity block, so the thickness is unchanged';
    status.textContent = `Filled from ${label}: ${thickness}; probe, wedge and angles where it has them.`;
    status.classList.toggle('is-warning', !item.block);
    status.hidden = false;
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
