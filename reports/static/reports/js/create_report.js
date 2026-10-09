// Report editor: setup/image formsets, results table, report types, section nav.

const reportForm = document.getElementById('report-form');

function readJson(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent); } catch (e) { return fallback; }
}

// ── Formset helpers ──────────────────────────────────────────────────────
// Django formsets need contiguous indexes (<prefix>-<n>-<field>) and TOTAL_FORMS to match.

function makeFormset({ prefix, container, template, blockSelector, titleSelector, titleText, removeSelector, onChange,
                       reorder = false }) {
    const totalForms = document.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    const namePattern = new RegExp(`^${prefix}-\\d+-`);
    const idPattern = new RegExp(`^id_${prefix}-\\d+-`);

    function renumber() {
        let index = 0;
        let blocks = [...container.querySelectorAll(blockSelector)];
        if (reorder) {
            // Moved blocks keep the formset's rule that saved forms come first; their place on the
            // page goes in each block's position field, which the server orders them by
            blocks.forEach((block, i) => {
                const position = block.querySelector('.block-position');
                if (position) position.value = i;
            });
            const saved = block => !!block.querySelector('input[name$="-id"]')?.value;
            blocks = [...blocks.filter(saved), ...blocks.filter(block => !saved(block))];
        }
        blocks.forEach(block => {
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
        if (reorder) container.classList.toggle('can-reorder', shown > 1);
        onChange(shown);
    }

    // Moving blocks (reorder): the arrows step past the next shown block, the grip drags
    function shownBlocks() {
        return [...container.querySelectorAll(blockSelector)].filter(block => !block.hidden);
    }

    function moveBlock(block, to) {
        const list = shownBlocks().filter(b => b !== block);
        if (!list.length) return;
        to = Math.max(0, Math.min(list.length, to));
        if (to < list.length) list[to].before(block);
        else list[list.length - 1].after(block);
        renumber();
        markDirty();
    }

    if (reorder) {
        container.addEventListener('click', e => {
            const button = e.target.closest('.block-up, .block-down');
            if (!button) return;
            const block = button.closest(blockSelector);
            const at = shownBlocks().indexOf(block);
            moveBlock(block, button.classList.contains('block-up') ? at - 1 : at + 1);
        });
        container.addEventListener('pointerdown', e => {
            const grip = e.target.closest('.block-grip');
            if (!grip || e.button !== 0) return;
            e.preventDefault();
            const block = grip.closest(blockSelector);
            const from = shownBlocks().indexOf(block);
            let to = from;
            grip.setPointerCapture(e.pointerId);
            block.classList.add('is-dragging-block');
            const clear = () => container.querySelectorAll('.drop-before, .drop-after')
                .forEach(b => b.classList.remove('drop-before', 'drop-after'));
            const move = ev => {
                const list = shownBlocks();
                to = list.length - 1;
                for (let k = 0; k < list.length; k++) {
                    const box = list[k].getBoundingClientRect();
                    if (ev.clientY < box.top + box.height / 2) { to = k > from ? k - 1 : k; break; }
                }
                clear();
                if (to !== from) list[to].classList.add(to > from ? 'drop-after' : 'drop-before');
            };
            const end = ev => {
                grip.removeEventListener('pointermove', move);
                grip.removeEventListener('pointerup', end);
                grip.removeEventListener('pointercancel', end);
                block.classList.remove('is-dragging-block');
                clear();
                if (ev.type === 'pointerup' && to !== from) moveBlock(block, to);
            };
            grip.addEventListener('pointermove', move);
            grip.addEventListener('pointerup', end);
            grip.addEventListener('pointercancel', end);
        });
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

// A saved setup's values and weld-form columns, fetched when it's picked (views/reports.py saved_setup_json)
async function fetchSavedSetup(pk) {
    const url = document.getElementById('report-form').dataset.savedSetupUrl.replace(/0\/values\.json$/, `${pk}/values.json`);
    const response = await fetch(url, { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `Setup #${pk} couldn't be loaded.`);
    return data;
}
window.fetchSavedSetup = fetchSavedSetup;

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

// Fills a setup block (by its form prefix, e.g. 'setups-0') with a setup's values
function fillSetupBlock(prefix, values) {
    Object.entries(values).forEach(([field, value]) => {
        const el = document.getElementById(`id_${prefix}-${field}`);
        if (el && el.type !== 'file') el.value = value ?? '';
    });
    // The values are in their own units
    const units = document.getElementById(`id_${prefix}-units`);
    if (units) window.Units.sync(units);
    // The wedge list depends on the probe: load it, then pick the setup's wedge
    const probe = document.getElementById(`id_${prefix}-catalogue_probe`);
    if (probe && values.catalogue_probe) {
        window.CatalogueSelect.setPair(probe, values.catalogue_probe, values.catalogue_wedge);
    }
    markDirty();
    window.FillMarks?.refresh();
}

// "Fill from saved setup…" copies a saved setup's values into this block
document.addEventListener('change', async e => {
    if (!e.target.classList.contains('setup-loader')) return;
    const select = e.target;
    const pk = select.value;
    select.value = '';
    if (!pk) return;
    try {
        fillSetupBlock(select.dataset.formPrefix, (await fetchSavedSetup(pk)).values);
    } catch (error) {
        showMessage(error.message);
    }
});

// "Import .nde" fills this block from the file's first inspection group, and a new setup block
// for each further group (catalogue probe / wedge matched, instrument from the scope library)
const setupNdeFile = document.getElementById('setup-nde-file');
let setupImportPrefix = null;
document.addEventListener('click', e => {
    const button = e.target.closest('.setup-nde-import');
    if (!button || !setupNdeFile) return;
    setupImportPrefix = button.dataset.formPrefix;
    setupNdeFile.click();
});
setupNdeFile?.addEventListener('change', async event => {
    event.stopPropagation();   // choosing a file isn't a change to the report itself
    const file = setupNdeFile.files[0];
    setupNdeFile.value = '';
    const prefix = setupImportPrefix;
    if (!file || !prefix) return;
    const block = document.getElementById(`id_${prefix}-units`)?.closest('.setup-block');
    const status = block?.querySelector('.setup-import-status');
    const show = (text, isError = false) => {
        if (!status) return;
        status.textContent = text;
        status.classList.toggle('text-danger', isError);
    };
    const body = new FormData();
    body.append('nde_file', file);
    body.append('units', document.getElementById(`id_${prefix}-units`)?.value || 'imperial');
    body.append('csrfmiddlewaretoken', reportForm.querySelector('[name=csrfmiddlewaretoken]').value);
    show(`Reading ${file.name}…`);
    try {
        const data = await (await fetch(setupNdeFile.dataset.url, { method: 'POST', body })).json();
        if (data.error) {
            show(data.error, true);
            return;
        }
        data.groups.forEach((group, i) => {
            let target = prefix;
            if (i > 0) {
                const added = setups.add();
                applyReportType();
                target = added.querySelector('.setup-loader').dataset.formPrefix;
            }
            fillSetupBlock(target, group.values);
        });
        const extra = data.groups.length - 1;
        show(`From ${data.filename}` + (extra ? ` (+${extra} more setup${extra === 1 ? '' : 's'})` : '')
             + (data.scope ? `; instrument from the scope library: ${data.scope}` : '') + '.');
    } catch (error) {
        show(`Couldn't read ${file.name}.`, true);
    }
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
    reorder: true,
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

// The Short Form's method description (a Text library entry): an empty Method takes its name,
// without a "(Short Form)" kept apart from the Long Form's entry of the same name
reportForm.addEventListener('change', e => {
    if (!e.target.matches('select[data-method-description]') || !e.target.value) return;
    const method = e.target.closest('.setup-block')?.querySelector('[name$="-title"]');
    const name = e.target.selectedOptions[0].text.replace(/\s*\((Short|Long) Form\)$/i, '');
    if (method && !method.value.trim()) method.value = name;
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
        field.hidden = isHidden(hiddenFields, field);
    });
    orderSections(type);
    applyTypeWording(type);
    // Empty fields outlined by where their value comes from (fill_marks.js), on the weld form
    reportForm.classList.toggle('fill-marks', Boolean(type.fill_marks));
    window.FillMarks?.refresh();
    updateActiveSection();
}

// A type's own wording (report_types.py labels): a field's label, a section's title
// ('section:<key>') or any [data-label] text; the usual wording is kept to switch back to.
// Also its fields shown in another section (field_homes), its suggestion lists (field_options)
// and, in setup blocks, groups whose every field it hides.
// Hidden for this type: by name, or 'setup.<name>' for a field of a setup block only
function isHidden(hiddenFields, field) {
    return hiddenFields.has(field.dataset.field)
        || (Boolean(field.closest('.setup-block')) && hiddenFields.has(`setup.${field.dataset.field}`));
}

// A type with its own section order (report_types.py ordered): sections and their menu links
// in that order; the others keep the editor's usual order (the order they were rendered in)
let usualOrder = null;
function orderSections(type) {
    const holder = reportForm.querySelector('.editor-sections');
    const nav = document.getElementById('section-nav');
    if (!holder) return;
    usualOrder ??= Array.from(holder.children);
    const rank = key => (type.ordered && type.sections.includes(key)) ? type.sections.indexOf(key) : -1;
    // The type's sections in its order, in the places its sections take; the rest stay put
    const mine = usualOrder.filter(el => rank(el.dataset.section) >= 0)
        .sort((a, b) => rank(a.dataset.section) - rank(b.dataset.section));
    let i = 0;
    usualOrder.map(el => (rank(el.dataset.section) >= 0 ? mine[i++] : el)).forEach(el => holder.appendChild(el));
    if (nav) {
        Array.from(holder.querySelectorAll(':scope > [data-section]')).forEach(section => {
            const link = nav.querySelector(`[data-nav-section="${section.dataset.section}"]`);
            if (link) nav.appendChild(link);
        });
    }
}

function relabel(el, text) {
    if (!el) return;
    if (el.dataset.usualText === undefined) el.dataset.usualText = el.textContent;
    el.textContent = text ?? el.dataset.usualText;
}

const fieldHomes = new Map();   // field element -> [its usual parent, the node it came before]

function applyTypeWording(type) {
    const labels = type.labels || {};
    const hidden = new Set(type.hidden_fields);
    // The page, and the templates new setup / image blocks are copied from
    const roots = [document, ...Array.from(document.querySelectorAll('template'), t => t.content)];

    roots.forEach(root => {
        root.querySelectorAll('[data-label]').forEach(el => relabel(el, labels[el.dataset.label]));
        root.querySelectorAll('[data-field]').forEach(field => {
            relabel(field.querySelector(':scope > label'), labels[field.dataset.field]);
            if (root !== document) field.hidden = isHidden(hidden, field);
        });
    });
    document.querySelectorAll('[data-section]').forEach(section => {
        relabel(section.querySelector(':scope > .panel-header .panel-title'), labels[`section:${section.dataset.section}`]);
    });
    document.querySelectorAll('[data-nav-section]').forEach(link => {
        const text = link.childNodes[0];   // the title; a count badge may follow
        if (text?.nodeType !== Node.TEXT_NODE) return;
        if (link.dataset.usualText === undefined) link.dataset.usualText = text.textContent;
        const own = labels[`section:${link.dataset.navSection}`];
        text.textContent = own ? `${own} ` : link.dataset.usualText;
    });

    // Fields living in another section for this type, put back for the others
    const homes = type.field_homes || {};
    reportForm.querySelectorAll('[data-field]').forEach(field => {
        const section = homes[field.dataset.field];
        const target = section && document.querySelector(`#sec-${section} .field-grid`);
        if (target) {
            if (!fieldHomes.has(field)) fieldHomes.set(field, [field.parentNode, field.nextSibling]);
            if (field.parentNode !== target) target.appendChild(field);
        } else if (fieldHomes.has(field)) {
            const [parent, before] = fieldHomes.get(field);
            parent.insertBefore(field, before);
            fieldHomes.delete(field);
        }
    });

    // Suggestions in text boxes (e.g. the corrosion form's methods and procedures)
    const options = type.field_options || {};
    roots.forEach(root => root.querySelectorAll('[data-field] input[type="text"], [data-field] input:not([type])').forEach(input => {
        const name = input.closest('[data-field]').dataset.field;
        const id = `options-${name}`;
        if (options[name]) {
            let list = document.getElementById(id);
            if (!list) {
                list = document.createElement('datalist');
                list.id = id;
                document.body.appendChild(list);
            }
            list.replaceChildren(...options[name].map(value => Object.assign(document.createElement('option'), { value })));
            input.setAttribute('list', id);
        } else if (input.getAttribute('list') === id) {
            input.removeAttribute('list');
        }
    }));

    // A setup block's group heading goes when the type hides every field in it
    roots.forEach(root => root.querySelectorAll('.cell-grid-head').forEach(head => {
        const grid = head.nextElementSibling;
        if (!grid?.classList.contains('cell-grid')) return;
        const cells = Array.from(grid.querySelectorAll(':scope > [data-field]'));
        head.hidden = grid.hidden = cells.length > 0 && cells.every(cell => cell.hidden);
    }));
}

reportTypeSelect.addEventListener('change', applyReportType);

// ── Report defaults (Preferences › Defaults) ─────────────────────────────────
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

// "Reload defaults": the defaults in use for the report's type, over what's there (app.js asks
// first). Fields the defaults leave blank keep their values; the weld grid gets the default
// columns only when it has none (overwriting columns could clobber imported probes).

function setValue(input, value) {
    if (!input || input.type === 'hidden' || input.type === 'file') return;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
}

function hasDefaults(type) {
    const { report, setup } = defaultsFor(type);
    const all = readJson('report-defaults', {})[type] || {};
    return Object.keys(report).length + Object.keys(setup).length + (all.probes || []).length + (all.groups || []).length > 0;
}

const reloadButton = document.getElementById('reload-defaults');
const reloadStatus = document.getElementById('reload-defaults-status');

function updateReloadButton() {
    reloadButton.disabled = !hasDefaults(reportTypeSelect.value);
    reloadButton.title = reloadButton.disabled
        ? 'No defaults in use for this report type (Preferences › Defaults)'
        : "Fill in the defaults in use for this report type again, over what's there";
}

reloadButton.addEventListener('click', async event => {
    if (!event.currentTarget.dataset.confirmed) return;   // app.js shows the confirmation first
    const { report, setup } = defaultsFor(reportTypeSelect.value);
    for (const [name, value] of Object.entries(report)) {
        if (value !== null && value !== '') setValue(reportForm.elements[name], value);
    }
    document.querySelectorAll('#setup-formset-container .setup-block').forEach(block => {
        const prefix = block.querySelector('[name$="-title"]')?.name.replace(/title$/, '');
        if (!prefix) return;
        const { catalogue_probe: probe, catalogue_wedge: wedge, ...rest } = setup;
        for (const [name, value] of Object.entries(rest)) {
            if (value !== null && value !== '') setValue(block.querySelector(`[name="${prefix}${name}"]`), value);
        }
        const probeSelect = block.querySelector(`[name="${prefix}catalogue_probe"]`);
        if (probe && probeSelect) window.CatalogueSelect.setPair(probeSelect, probe, wedge);
        const units = block.querySelector(`select[name="${prefix}units"]`);
        if (units) window.Units.sync(units);
    });
    const columnsAdded = await window.WeldGrid?.reloadDefaultColumns();
    // Let the pages' own scripts catch up (TCG distances, N/A greying, …)
    reportForm.elements.tcg_thickness?.dispatchEvent(new Event('input', { bubbles: true }));
    markDirty();
    window.FillMarks?.refresh();
    reloadStatus.textContent = 'Defaults reloaded' + ({
        added: ', with their probe and group columns.',
        updated: ', including the probe and group columns.',
    }[columnsAdded] || '.');
    setTimeout(() => { reloadStatus.textContent = ''; }, 6000);
});
reportTypeSelect.addEventListener('change', updateReloadButton);
updateReloadButton();

// Section nav: section_nav.js (shared with Preferences › Defaults) highlights the section in view

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
