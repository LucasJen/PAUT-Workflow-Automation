// NDE import page: drag-and-drop upload, and filling the setup form from the parsed file.
// Values are extracted server-side (reports/services/nde_parser.py) per group and unit system;
// this script only picks which set to show.

// ── Upload ───────────────────────────────────────────────────────────────

const uploadForm = document.getElementById('nde-upload-form');
const fileInput = document.getElementById('nde_file');
const dropZone = document.getElementById('drop-zone');

function submitFile() {
    const file = fileInput.files[0];
    if (!file) return;
    dropZone.classList.add('busy');
    document.getElementById('drop-hint').textContent = `Reading ${file.name}…`;
    uploadForm.submit();
}

fileInput.addEventListener('change', submitFile);

['dragenter', 'dragover'].forEach(type => dropZone.addEventListener(type, e => {
    e.preventDefault();
    dropZone.classList.add('dragging');
}));

['dragleave', 'drop'].forEach(type => dropZone.addEventListener(type, () => dropZone.classList.remove('dragging')));

dropZone.addEventListener('drop', e => {
    e.preventDefault();
    if (!e.dataTransfer.files.length) return;
    fileInput.files = e.dataTransfer.files;
    submitFile();
});

// ── Fill the setup form ──────────────────────────────────────────────────

const groupsEl = document.getElementById('nde-groups');
const groups = groupsEl ? JSON.parse(groupsEl.textContent) : [];
const groupSelect = document.getElementById('nde-group');
const setupForm = document.getElementById('nde-setup-form');
let unit = 'imperial';
let filledFields = [];

function fillForm() {
    const group = groups[groupSelect ? Number(groupSelect.value) : 0];
    if (!group) return;
    const values = group.values[unit] || {};

    // Clear values from a previously shown group so nothing carries over between groups
    filledFields.forEach(name => {
        const el = setupForm.querySelector(`[name="${name}"]`);
        if (el) el.value = '';
        el?.closest('.field')?.classList.remove('from-file');
    });

    filledFields = [];
    Object.entries(values).forEach(([name, value]) => {
        const el = setupForm.querySelector(`[name="${name}"]`);
        if (!el || name === 'catalogue_wedge') return;  // the wedge is set after its list loads
        el.value = value;
        el.closest('.field')?.classList.add('from-file');
        filledFields.push(name);
    });
    // The file's values are already in the chosen units; record that without converting them
    const unitsSelect = setupForm.querySelector('select[name="units"]');
    if (unitsSelect) window.Units.sync(unitsSelect);
    const probeSelect = setupForm.querySelector('[name="catalogue_probe"]');
    if (probeSelect && values.catalogue_probe) {
        window.CatalogueSelect.setPair(probeSelect, values.catalogue_probe, values.catalogue_wedge || null);
        if (values.catalogue_wedge) {
            setupForm.querySelector('[name="catalogue_wedge"]')?.closest('.field')?.classList.add('from-file');
            filledFields.push('catalogue_wedge');
        }
    }
    renderMatch(group);
}

// ── Catalogue match ──────────────────────────────────────────────────────
// What the file's probe and wedge matched in the catalogue (reports/views/nde.py), with
// 'Add to catalogue' for ones the catalogue doesn't have and a warning when the catalogue
// wedge's geometry differs from the file's.

const matchBox = document.getElementById('catalogue-match');

function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text) el.textContent = text;
    return el;
}

function matchLine(group, kind) {
    const info = group.catalogue[kind];
    const noun = kind === 'probe' ? 'Probe' : 'Wedge';
    const line = element('div', 'catalogue-match-line');
    if (!info) {
        line.append(element('span', 'text-muted-cell', `${noun}: not recorded in the file.`));
        return line;
    }
    if (info.pk) {
        line.append(element('i', 'bi bi-check-circle-fill text-success'), ` ${noun}: `, element('strong', '', info.name),
                    element('span', 'text-muted-cell', ` (${info.how}${info.file_name && info.file_name !== info.name ? `, file: ${info.file_name}` : ''})`));
        if (info.differences && info.differences.length) {
            const warn = element('div', 'catalogue-match-warning');
            warn.append(element('i', 'bi bi-exclamation-triangle-fill'),
                        ' Geometry differs from the file; the catalogue values are used: ');
            warn.append(info.differences.map(([label, catalogue, file]) => `${label} ${catalogue} in catalogue, ${file} in file`).join('; ') + '.');
            if (info.suggestion) {
                const use = element('button', 'btn btn-sm btn-outline-secondary', `Use ${info.suggestion.name} instead`);
                use.type = 'button';
                use.title = 'This catalogue wedge has the geometry the file records';
                use.addEventListener('click', () => {
                    group.catalogue.wedge = { ...info.suggestion, how: 'its geometry matches the file', differences: [],
                                              file_name: info.file_name };
                    Object.values(group.values).forEach(values => { values.catalogue_wedge = info.suggestion.pk; });
                    fillForm();
                });
                warn.append(' The file\'s geometry matches ', element('strong', '', info.suggestion.name), '. ', use);
            }
            line.append(warn);
        }
        return line;
    }
    line.append(element('i', 'bi bi-question-circle-fill text-warning'), ` ${noun} `,
                element('strong', '', info.file_name || '(no name)'), ' is not in the catalogue. ');
    const add = element('button', 'btn btn-sm btn-secondary', 'Add to catalogue');
    add.type = 'button';
    add.addEventListener('click', () => addToCatalogue(group, kind, add));
    line.append(add);
    return line;
}

function renderMatch(group) {
    if (!matchBox || !group.catalogue) return;
    matchBox.replaceChildren(element('h3', 'panel-subtitle mt-0', 'Catalogue match'),
                             matchLine(group, 'probe'), matchLine(group, 'wedge'));
}

async function addToCatalogue(group, kind, button) {
    const info = group.catalogue[kind];
    button.disabled = true;
    const response = await fetch(matchBox.dataset.addUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': setupForm.querySelector('[name=csrfmiddlewaretoken]').value,
        },
        body: JSON.stringify({ kind, fields: info.file_fields, file: matchBox.dataset.file }),
    });
    if (!response.ok) {
        button.disabled = false;
        button.textContent = 'Could not add; try again';
        return;
    }
    const { pk, name } = await response.json();
    group.catalogue[kind] = { pk, name, how: 'added from this file', file_name: info.file_name, differences: [] };
    const field = kind === 'probe' ? 'catalogue_probe' : 'catalogue_wedge';
    Object.values(group.values).forEach(values => { values[field] = pk; });
    const probeSelect = setupForm.querySelector('[name="catalogue_probe"]');
    if (kind === 'probe' && ![...probeSelect.options].some(o => o.value === String(pk))) {
        probeSelect.append(new Option(name, pk));
    }
    fillForm();
}

function setUnit(next) {
    unit = next;
    document.getElementById('btn-imperial').className = `btn ${unit === 'imperial' ? 'btn-primary' : 'btn-outline-primary'}`;
    document.getElementById('btn-metric').className = `btn ${unit === 'metric' ? 'btn-primary' : 'btn-outline-primary'}`;
    fillForm();
}

// ── Clear setup ──────────────────────────────────────────────────────────
// The button reloads a fresh import page; ask first only when there is something to lose.

const clearButton = document.getElementById('clear-setup');

function updateClearConfirm() {
    // Something to lose: values from a file, values returned by a failed save, or typed changes
    const edited = Array.from(setupForm.querySelectorAll('input:not([type=hidden]), textarea'))
        .some(el => el.value !== el.defaultValue);
    if (groups.length || setupForm.dataset.bound || edited) {
        clearButton.dataset.confirm = 'Clear all setup fields? Anything not saved will be lost.';
        clearButton.dataset.confirmLabel = 'Clear';
    } else {
        delete clearButton.dataset.confirm;
    }
}

setupForm.addEventListener('input', updateClearConfirm);

if (groups.length) {
    document.querySelectorAll('[data-unit]').forEach(button => {
        button.addEventListener('click', () => setUnit(button.dataset.unit));
    });
    groupSelect?.addEventListener('change', fillForm);
    fillForm();
}

updateClearConfirm();
