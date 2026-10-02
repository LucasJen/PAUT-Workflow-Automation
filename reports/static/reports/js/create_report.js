// Report editor: setup/image formsets, results table, report types, section nav.

const reportForm = document.getElementById('report-form');

function readJson(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent); } catch (e) { return fallback; }
}

// ── Formset helpers ──────────────────────────────────────────────────────
// Django formsets need contiguous indexes (<prefix>-<n>-<field>) and TOTAL_FORMS to match.

function makeFormset({ prefix, container, template, blockSelector, titleSelector, titleText, removeSelector, onChange }) {
    const totalForms = document.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    const namePattern = new RegExp(`^${prefix}-\\d+-`);
    const idPattern = new RegExp(`^id_${prefix}-\\d+-`);

    function renumber() {
        let index = 0;
        container.querySelectorAll(blockSelector).forEach(block => {
            block.querySelectorAll('input, select, textarea').forEach(el => {
                if (el.name) el.name = el.name.replace(namePattern, `${prefix}-${index}-`);
                if (el.id) el.id = el.id.replace(idPattern, `id_${prefix}-${index}-`);
            });
            block.querySelectorAll('label[for]').forEach(label => {
                label.htmlFor = label.htmlFor.replace(idPattern, `id_${prefix}-${index}-`);
            });
            const loader = block.querySelector('.setup-loader');
            if (loader) loader.dataset.formPrefix = `${prefix}-${index}`;
            block.dataset.formIndex = index;
            index++;
        });
        totalForms.value = index;

        // Titles count only blocks still shown (removed saved blocks are hidden, not deleted)
        let shown = 0;
        container.querySelectorAll(blockSelector).forEach(block => {
            if (block.hidden) return;
            shown++;
            const title = block.querySelector(titleSelector);
            if (title) title.textContent = titleText(shown);
        });
        onChange(shown);
    }

    function add() {
        const index = parseInt(totalForms.value, 10);
        const html = template.innerHTML.replace(/__prefix__/g, index);
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const block = wrapper.firstElementChild;
        container.appendChild(block);
        renumber();
        return block;
    }

    container.addEventListener('click', e => {
        const button = e.target.closest(removeSelector);
        if (!button) return;
        const block = button.closest(blockSelector);
        const idInput = block.querySelector('input[name$="-id"]');
        if (idInput && idInput.value) {
            // Saved row: mark for deletion and hide so the server deletes it on save
            const deleteInput = block.querySelector('input[name$="-DELETE"]');
            if (deleteInput) deleteInput.checked = true;
            block.hidden = true;
        } else {
            block.remove();
        }
        renumber();
        markDirty();
    });

    renumber();
    return { add, renumber };
}

// ── Setups ───────────────────────────────────────────────────────────────

const savedSetupValues = readJson('saved-setup-values', {});

const setups = makeFormset({
    prefix: 'setups',
    container: document.getElementById('setup-formset-container'),
    template: document.getElementById('setup-empty-form'),
    blockSelector: '.setup-block',
    titleSelector: '.setup-block-title',
    titleText: n => `Setup #${n}`,
    removeSelector: '.remove-setup',
    onChange: n => { document.getElementById('setups-count').textContent = n || ''; },
});

document.getElementById('add-setup').addEventListener('click', () => {
    const block = setups.add();
    applyReportType();
    applySetupDefaults(block, {}, defaultsFor(reportTypeSelect.value).setup);
    block.scrollIntoView({ behavior: 'smooth', block: 'start' });
    markDirty();
});

// "Fill from saved setup…" copies a saved setup's values into this block
document.addEventListener('change', e => {
    if (!e.target.classList.contains('setup-loader')) return;
    const select = e.target;
    const values = savedSetupValues[select.value];
    if (!values) return;
    const prefix = select.dataset.formPrefix;
    Object.entries(values).forEach(([field, value]) => {
        const el = document.getElementById(`id_${prefix}-${field}`);
        if (el) el.value = value ?? '';
    });
    // The loaded setup's values are in its own units
    const units = document.getElementById(`id_${prefix}-units`);
    if (units) window.Units.sync(units);
    // The wedge list depends on the probe: load it, then pick the setup's wedge
    const probe = document.getElementById(`id_${prefix}-catalogue_probe`);
    if (probe && values.catalogue_probe) {
        window.CatalogueSelect.setPair(probe, values.catalogue_probe, values.catalogue_wedge);
    }
    select.value = '';
    markDirty();
});

// ── Equipment drawings and photo-summary images ──────────────────────────

const imageContainer = document.getElementById('image-formset-container');

const drawings = makeFormset({
    prefix: 'drawings',
    container: document.getElementById('drawing-formset-container'),
    template: document.getElementById('drawing-empty-form'),
    blockSelector: '.image-block',
    titleSelector: '.image-num',
    titleText: n => String(n),
    removeSelector: '.remove-image',
    onChange: n => { document.getElementById('drawings-count').textContent = n || ''; },
});

const images = makeFormset({
    prefix: 'images',
    container: imageContainer,
    template: document.getElementById('image-empty-form'),
    blockSelector: '.image-block',
    titleSelector: '.image-num',
    titleText: n => String(n),
    removeSelector: '.remove-image',
    onChange: n => { document.getElementById('images-count').textContent = n || ''; },
});

// ── Personnel ────────────────────────────────────────────────────────────

const personContainer = document.getElementById('person-formset-container');

const people = makeFormset({
    prefix: 'people',
    container: personContainer,
    template: document.getElementById('person-empty-form'),
    blockSelector: '.person-row',
    titleSelector: '.no-title',
    titleText: () => '',
    removeSelector: '.remove-person',
    onChange: n => {
        document.getElementById('personnel-count').textContent = n || '';
        document.getElementById('person-empty-hint').hidden = n > 0;
    },
});

document.getElementById('add-person').addEventListener('click', () => {
    const row = people.add();
    row.querySelector('input[name$="-name"]').focus();
    markDirty();
});

// Picking a name used on an earlier report fills in their certification (if still blank)
personContainer.addEventListener('change', e => {
    if (!e.target.matches('input[name$="-name"]')) return;
    const known = Array.from(document.querySelectorAll('#known-people option')).find(o => o.value === e.target.value.trim());
    const cert = e.target.closest('.person-row').querySelector('input[name$="-certification"]');
    if (known && cert && !cert.value.trim()) cert.value = known.dataset.certification || '';
});

// The weld form's technician / reviewer: the same for its two name fields
reportForm.addEventListener('change', e => {
    const certName = e.target.dataset?.certField;
    if (!certName) return;
    const known = Array.from(document.querySelectorAll('#known-people option')).find(o => o.value === e.target.value.trim());
    const cert = reportForm.elements[certName];
    if (known && cert && !cert.value.trim()) cert.value = known.dataset.certification || '';
});

document.getElementById('add-drawing').addEventListener('click', () => {
    drawings.add();
    markDirty();
});

document.getElementById('add-image').addEventListener('click', () => {
    images.add();
    refreshScanSelects();
    markDirty();
});

// Preview a newly chosen image file (drawings and scan images)
document.addEventListener('change', e => {
    if (e.target.type !== 'file' || !e.target.closest('.image-block')) return;
    const file = e.target.files[0];
    const block = e.target.closest('.image-block');
    if (!file || !block) return;
    const previewWrap = block.querySelector('.image-preview-wrap');
    const thumb = block.querySelector('.image-thumb');
    const reader = new FileReader();
    reader.onload = ev => {
        thumb.src = ev.target.result;
        previewWrap.hidden = false;
    };
    reader.readAsDataURL(file);
});

// ── Results table ────────────────────────────────────────────────────────

const resultsColHeaders = document.getElementById('results-col-headers');
const resultsTheadRow = document.getElementById('results-thead-row');
const resultsTbody = document.getElementById('results-tbody');
const resultsEmptyHint = document.getElementById('results-empty-hint');

let columns = [];  // column header strings

// The Results/Comments column holds paragraphs, so it gets a text box that grows as you type
const LONG_COLUMN = /result|comment/i;

function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight + 2}px`;
}

function cellInput(placeholder, value) {
    const td = document.createElement('td');
    td.className = 'result-cell';
    const long = LONG_COLUMN.test(placeholder || '');
    const input = document.createElement(long ? 'textarea' : 'input');
    if (long) {
        input.rows = 2;
        input.addEventListener('input', () => autoGrow(input));
        requestAnimationFrame(() => autoGrow(input));
        td.classList.add('result-cell-long');
    } else {
        input.type = 'text';
    }
    input.className = 'result-cell-input';
    input.placeholder = placeholder || '';
    input.value = value || '';
    td.appendChild(input);
    return td;
}

function renderResultsTable() {
    resultsTheadRow.innerHTML = '';
    columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col;
        resultsTheadRow.appendChild(th);
    });
    if (columns.length) resultsTheadRow.appendChild(document.createElement('th'));

    // Keep every row's cell count in step with the columns
    resultsTbody.querySelectorAll('tr').forEach(tr => {
        const actions = tr.querySelector('td.result-actions');
        let cells = tr.querySelectorAll('td.result-cell');
        for (let i = cells.length; i < columns.length; i++) tr.insertBefore(cellInput(columns[i]), actions);
        cells = tr.querySelectorAll('td.result-cell');
        for (let i = columns.length; i < cells.length; i++) cells[i].remove();
        tr.querySelectorAll('.result-cell-input').forEach((input, ci) => { input.placeholder = columns[ci] || ''; });
    });

    resultsEmptyHint.hidden = columns.length > 0;
    document.getElementById('add-results-row').disabled = columns.length === 0;
    refreshScanSelects();
}

// ── Photo summary: Scan ID options and comments come from the results table ──
// Same rules as reports/results.py: Scan ID is the first column; comments come from the
// column whose header mentions "result" or "comment", otherwise the last column.

function resultsScanRows() {
    const headers = Array.from(resultsColHeaders.querySelectorAll('.col-header-input')).map(i => i.value);
    let commentIndex = headers.findIndex((h, i) => i > 0 && /result|comment/i.test(h));
    if (commentIndex < 0) commentIndex = headers.length - 1;
    return Array.from(resultsTbody.querySelectorAll('tr')).map(tr => {
        const cells = Array.from(tr.querySelectorAll('.result-cell-input')).map(i => i.value);
        return { id: (cells[0] || '').trim(), comments: commentIndex > 0 ? (cells[commentIndex] || '') : '' };
    }).filter(row => row.id);
}

function refreshScanSelects() {
    const rows = resultsScanRows();
    const byId = new Map(rows.map(r => [r.id, r.comments]));
    imageContainer.querySelectorAll('.image-block').forEach(block => {
        const select = block.querySelector('select[name$="-scan_id"]');
        if (!select) return;
        const current = select.value;
        select.innerHTML = '';
        select.add(new Option('— Select scan —', ''));
        byId.forEach((_, id) => select.add(new Option(id, id)));
        if (current && !byId.has(current)) select.add(new Option(`${current} (not in results table)`, current));
        select.value = current;

        const preview = block.querySelector('.scan-comments');
        if (!preview) return;
        if (!current) {
            preview.textContent = 'Pick a Scan ID to use that row\'s comments.';
            preview.classList.add('missing');
        } else if (!byId.has(current)) {
            preview.textContent = 'This Scan ID is no longer in the results table, so no comments will be shown.';
            preview.classList.add('missing');
        } else {
            preview.textContent = byId.get(current) || '(no comments in this row)';
            preview.classList.toggle('missing', !byId.get(current));
        }
    });
}

imageContainer.addEventListener('change', e => {
    if (e.target.matches('select[name$="-scan_id"]')) refreshScanSelects();
});
resultsTbody.addEventListener('input', refreshScanSelects);

function addResultsRow(values) {
    const tr = document.createElement('tr');
    columns.forEach((col, ci) => tr.appendChild(cellInput(col, values && values[ci])));
    const actions = document.createElement('td');
    actions.className = 'result-actions';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn-icon btn-sm';
    remove.title = 'Remove row';
    remove.innerHTML = '<i class="bi bi-x-lg"></i>';
    remove.addEventListener('click', () => { tr.remove(); refreshScanSelects(); markDirty(); });
    actions.appendChild(remove);
    tr.appendChild(actions);
    resultsTbody.appendChild(tr);
    refreshScanSelects();
}

function addResultsColumn(header, locked = false) {
    columns.push(header || '');

    const wrap = document.createElement('div');
    wrap.className = 'col-header-wrap';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm col-header-input';
    input.value = header || '';
    input.placeholder = `Column ${columns.length}`;
    input.addEventListener('input', () => {
        columns[indexOfWrap(wrap)] = input.value;
        renderResultsTable();
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn-icon btn-sm col-remove-btn';
    remove.title = 'Remove column';
    remove.innerHTML = '<i class="bi bi-x-lg"></i>';
    remove.addEventListener('click', () => {
        const ci = indexOfWrap(wrap);
        columns.splice(ci, 1);
        wrap.remove();
        resultsTbody.querySelectorAll('tr').forEach(tr => {
            const cell = tr.querySelectorAll('td.result-cell')[ci];
            if (cell) cell.remove();
        });
        renderResultsTable();
        markDirty();
    });

    if (locked) {
        input.readOnly = true;  // fixed by the report type
        remove.hidden = true;
    }
    wrap.append(input, remove);
    resultsColHeaders.appendChild(wrap);
    renderResultsTable();
}

function indexOfWrap(wrap) {
    return Array.from(resultsColHeaders.children).indexOf(wrap);
}

document.getElementById('add-results-col').addEventListener('click', () => {
    addResultsColumn('');
    resultsColHeaders.lastElementChild.querySelector('input').focus();
    markDirty();
});

document.getElementById('add-results-row').addEventListener('click', () => {
    addResultsRow(null);
    markDirty();
});

// Report types with fixed results columns (e.g. HIC) lock the headings; the server has
// already fitted saved tables to them (reports/results.py::fit_to_columns)
function fixedResultsHeadings() {
    const types = readJson('report-types', {});
    const select = document.getElementById('id_report_type');
    const type = types[select && select.value] || Object.values(types)[0];
    const cols = type && type.results_columns;
    return cols && cols.length ? cols.map(c => c.heading) : null;
}

(function loadResults() {
    const data = readJson('results-initial-data', {});
    const fixed = fixedResultsHeadings();
    (fixed || data.columns || []).forEach(col => addResultsColumn(col, !!fixed));
    (data.rows || []).forEach(row => addResultsRow(row));
    if (fixed) {
        document.getElementById('add-results-col').hidden = true;
        resultsColHeaders.hidden = true;  // the table header already shows the fixed headings
    }
    renderResultsTable();
})();

// ── Report types: show only the sections/fields the chosen type uses ────

const reportTypes = readJson('report-types', {});
const reportTypeSelect = document.getElementById('id_report_type');

function applyReportType() {
    const type = reportTypes[reportTypeSelect.value] || Object.values(reportTypes)[0];
    if (!type) return;
    const hiddenFields = new Set(type.hidden_fields);

    document.querySelectorAll('[data-section]').forEach(section => {
        section.hidden = !type.sections.includes(section.dataset.section);
    });
    document.querySelectorAll('[data-nav-section]').forEach(link => {
        link.hidden = !type.sections.includes(link.dataset.navSection);
    });
    reportForm.querySelectorAll('.editor-sections [data-field]').forEach(field => {
        field.hidden = hiddenFields.has(field.dataset.field);
    });
    updateActiveSection();
}

reportTypeSelect.addEventListener('change', applyReportType);

// ── Report defaults (Library › Defaults) ─────────────────────────────────
// A new report opens with its type's defaults (filled by the server). Switching the type swaps
// in the new type's defaults, but only where a field is still empty or still holds the old
// type's default; anything typed or filled from elsewhere stays.

function defaultsFor(type) {
    const all = readJson('report-defaults', {});
    return { report: (all[type] || {}).report || {}, setup: (all[type] || {}).setup || {} };
}

function swapDefault(input, before, after) {
    if (!input || input.type === 'hidden' || input.type === 'file') return;
    const current = input.type === 'checkbox' ? input.checked : input.value;
    const untouched = input.type === 'checkbox'
        ? current === Boolean(before)
        : current === '' || current === String(before ?? '');
    if (!untouched || after === undefined) return;
    if (input.type === 'checkbox') input.checked = Boolean(after);
    else input.value = after ?? '';
}

function applySetupDefaults(block, before, after) {
    const prefix = block.querySelector('[name$="-title"]')?.name.replace(/title$/, '');
    if (!prefix) return;
    const { catalogue_probe: probe, catalogue_wedge: wedge, ...rest } = after;
    for (const name of new Set([...Object.keys(before), ...Object.keys(rest)])) {
        if (name === 'catalogue_probe' || name === 'catalogue_wedge') continue;
        swapDefault(block.querySelector(`[name="${prefix}${name}"]`), before[name], rest[name]);
    }
    const probeSelect = block.querySelector(`[name="${prefix}catalogue_probe"]`);
    if (probe && probeSelect && !probeSelect.value) window.CatalogueSelect.setPair(probeSelect, probe, wedge);
    const units = block.querySelector(`select[name="${prefix}units"]`);
    if (units) window.Units.sync(units);
}

let defaultsType = reportTypeSelect.value;
reportTypeSelect.addEventListener('change', () => {
    const before = defaultsFor(defaultsType);
    const after = defaultsFor(reportTypeSelect.value);
    for (const name of new Set([...Object.keys(before.report), ...Object.keys(after.report)])) {
        swapDefault(reportForm.elements[name], before.report[name], after.report[name]);
    }
    document.querySelectorAll('#setup-formset-container .setup-block').forEach(block => {
        applySetupDefaults(block, before.setup, after.setup);
    });
    defaultsType = reportTypeSelect.value;
});

// ── Section nav: highlight the section currently in view ─────────────────

const navLinks = Array.from(document.querySelectorAll('[data-nav-section]'));

function updateActiveSection() {
    const sections = Array.from(document.querySelectorAll('.editor-section')).filter(s => !s.hidden);
    const marker = window.innerHeight * 0.3;
    let current = sections[0];
    sections.forEach(section => {
        if (section.getBoundingClientRect().top <= marker) current = section;
    });
    // At the bottom of the page the last section is current even if short
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) current = sections[sections.length - 1];
    navLinks.forEach(link => link.classList.toggle('active', !!current && link.dataset.navSection === current.dataset.section));
}

window.addEventListener('scroll', updateActiveSection, { passive: true });
window.addEventListener('resize', updateActiveSection);

// ── Unsaved changes guard ─────────────────────────────────────────────────

let dirty = false;
const unsavedIndicator = document.getElementById('unsaved-indicator');

function markDirty() {
    dirty = true;
    unsavedIndicator.hidden = false;
    // Downloading now would give the last saved version, so ask first (app.js shows the dialog)
    ['download-link', 'pdf-link'].forEach(id => {
        const link = document.getElementById(id);
        if (link) {
            link.dataset.confirm = "You have unsaved changes. The download won't include them until you save.";
            link.dataset.confirmLabel = 'Download anyway';
        }
    });
}

reportForm.addEventListener('input', markDirty);
reportForm.addEventListener('change', e => { if (!e.target.classList.contains('setup-loader')) markDirty(); });

window.addEventListener('beforeunload', e => {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = '';
});

// ── Submit: serialise the results table ──────────────────────────────────

reportForm.addEventListener('submit', () => {
    const cols = Array.from(resultsColHeaders.querySelectorAll('.col-header-input')).map(i => i.value);
    const rows = Array.from(resultsTbody.querySelectorAll('tr')).map(tr =>
        Array.from(tr.querySelectorAll('.result-cell-input')).map(i => i.value));
    document.getElementById('results-columns-input').value = JSON.stringify(cols);
    document.getElementById('results-rows-input').value = JSON.stringify(rows);
    dirty = false;
});

// ── Download after "Save & download" ─────────────────────────────────────

const downloadLink = document.getElementById('download-link');

if (downloadLink?.hasAttribute('data-auto-download')) {
    // Drop ?download=1 so reloading the page doesn't download again
    const url = new URL(window.location.href);
    url.searchParams.delete('download');
    window.history.replaceState(null, '', url);
    downloadLink.click();  // a download link, so the browser stays on this page
}

applyReportType();
