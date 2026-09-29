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
        if (!el) return;
        el.value = value;
        el.closest('.field')?.classList.add('from-file');
        filledFields.push(name);
    });
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
