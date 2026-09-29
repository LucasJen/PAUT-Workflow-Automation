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
    onChange: n => { document.getElementById('setup-count').textContent = n || ''; },
});

document.getElementById('add-setup').addEventListener('click', () => {
    const block = setups.add();
    applyReportType();
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
    select.value = '';
    markDirty();
});

// ── Images ───────────────────────────────────────────────────────────────

const imageContainer = document.getElementById('image-formset-container');

const images = makeFormset({
    prefix: 'images',
    container: imageContainer,
    template: document.getElementById('image-empty-form'),
    blockSelector: '.image-block',
    titleSelector: '.image-num',
    titleText: n => String(n),
    removeSelector: '.remove-image',
    onChange: n => { document.getElementById('image-count').textContent = n || ''; },
});

document.getElementById('add-image').addEventListener('click', () => {
    images.add();
    markDirty();
});

// Preview a newly chosen image file
imageContainer.addEventListener('change', e => {
    if (e.target.type !== 'file') return;
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

function cellInput(placeholder, value) {
    const td = document.createElement('td');
    td.className = 'result-cell';
    const input = document.createElement('input');
    input.type = 'text';
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
        tr.querySelectorAll('td.result-cell input').forEach((input, ci) => { input.placeholder = columns[ci] || ''; });
    });

    resultsEmptyHint.hidden = columns.length > 0;
    document.getElementById('add-results-row').disabled = columns.length === 0;
}

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
    remove.addEventListener('click', () => { tr.remove(); markDirty(); });
    actions.appendChild(remove);
    tr.appendChild(actions);
    resultsTbody.appendChild(tr);
}

function addResultsColumn(header) {
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

(function loadResults() {
    const data = readJson('results-initial-data', {});
    (data.columns || []).forEach(col => addResultsColumn(col));
    (data.rows || []).forEach(row => addResultsRow(row));
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
        Array.from(tr.querySelectorAll('td.result-cell input')).map(i => i.value));
    document.getElementById('results-columns-input').value = JSON.stringify(cols);
    document.getElementById('results-rows-input').value = JSON.stringify(rows);
    dirty = false;
});

applyReportType();
