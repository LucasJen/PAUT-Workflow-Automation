// ── Setup Formset ──────────────────────────────────────────────────────────

const setupContainer = document.getElementById('setup-formset-container');
const setupEmptyForm = document.getElementById('setup-empty-form');
const setupTotalForms = document.querySelector('[name="setups-TOTAL_FORMS"]');

function renumberSetups() {
    const blocks = setupContainer.querySelectorAll('.setup-block');
    let formIndex = 0;
    blocks.forEach(block => {
        block.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.name) el.name = el.name.replace(/^setups-\d+-/, `setups-${formIndex}-`);
            if (el.id) el.id = el.id.replace(/^id_setups-\d+-/, `id_setups-${formIndex}-`);
        });
        block.querySelectorAll('label[for]').forEach(label => {
            label.htmlFor = label.htmlFor.replace(/^id_setups-\d+-/, `id_setups-${formIndex}-`);
        });
        const loader = block.querySelector('.setup-loader');
        if (loader) loader.dataset.formPrefix = `setups-${formIndex}`;
        block.dataset.formIndex = formIndex;
        const title = block.querySelector('.setup-block-title');
        if (title) title.textContent = `Setup #${formIndex + 1}`;
        formIndex++;
    });
    setupTotalForms.value = formIndex;
}

document.getElementById('add-setup').addEventListener('click', () => {
    const count = parseInt(setupTotalForms.value);
    const emptyBlock = setupEmptyForm.querySelector('.setup-block');
    const clone = emptyBlock.cloneNode(true);

    // Replace __prefix__ with real index
    clone.innerHTML = clone.innerHTML.replace(/__prefix__/g, count);
    clone.dataset.formIndex = count;
    clone.querySelector('.setup-block-title').textContent = `Setup #${count + 1}`;

    setupContainer.appendChild(clone);
    setupTotalForms.value = count + 1;
});

setupContainer.addEventListener('click', e => {
    if (!e.target.classList.contains('remove-setup')) return;
    const block = e.target.closest('.setup-block');
    if (!block) return;

    const idInput = block.querySelector('input[name$="-id"]');
    if (idInput && idInput.value) {
        // Existing saved setup — mark DELETE and hide
        const deleteInput = block.querySelector('input[name$="-DELETE"]');
        if (deleteInput) deleteInput.checked = true;
        block.style.display = 'none';
    } else {
        block.remove();
    }
    renumberSetups();
});

// Per-block "Load from saved setup" dropdown
document.addEventListener('change', e => {
    if (!e.target.classList.contains('setup-loader')) return;
    const select = e.target;
    const opt = select.options[select.selectedIndex];
    if (!opt.value) return;

    const prefix = select.dataset.formPrefix;
    const fields = [
        'manufacturer', 'scope_platform', 'scope_model', 'scope_serial',
        'transducer_model', 'transducer_serial', 'probe_diameter',
        'wedge_model', 'wedge_angle',
        'foc_depth', 'wave_propagation', 'freq', 'elements',
        'x_res', 'y_res', 'scan_length', 'scan_width',
        'angle_step', 'angle_range', 'sound_velocity', 'gain', 'ref_gain', 'voltage',
        'specimen_od', 'specimen_thickness',
        'cal_material', 'material_temp', 'cal_block_type', 'cal_block_serial',
        'surface_prep', 'tr_min', 'tr_max',
    ];
    fields.forEach(field => {
        const el = document.getElementById(`id_${prefix}-${field}`);
        if (el) el.value = opt.dataset[field] || '';
    });
});


// ── Image Formset ──────────────────────────────────────────────────────────

const imageContainer = document.getElementById('image-formset-container');
const imageEmptyForm = document.getElementById('image-empty-form');
const imageTotalForms = document.querySelector('[name="images-TOTAL_FORMS"]');

function renumberImages() {
    const blocks = imageContainer.querySelectorAll('.image-block');
    let formIndex = 0;
    blocks.forEach(block => {
        block.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.name) el.name = el.name.replace(/^images-\d+-/, `images-${formIndex}-`);
            if (el.id) el.id = el.id.replace(/^id_images-\d+-/, `id_images-${formIndex}-`);
        });
        block.querySelectorAll('label[for]').forEach(label => {
            label.htmlFor = label.htmlFor.replace(/^id_images-\d+-/, `id_images-${formIndex}-`);
        });
        block.dataset.formIndex = formIndex;
        const title = block.querySelector('.image-block-title');
        if (title) title.textContent = `Image ${formIndex + 1}`;
        formIndex++;
    });
    imageTotalForms.value = formIndex;
}

document.getElementById('add-image').addEventListener('click', () => {
    const count = parseInt(imageTotalForms.value);
    const emptyBlock = imageEmptyForm.querySelector('.image-block');
    const clone = emptyBlock.cloneNode(true);

    clone.innerHTML = clone.innerHTML.replace(/__prefix__/g, count);
    clone.dataset.formIndex = count;
    const numSpan = clone.querySelector('.image-num');
    if (numSpan) numSpan.textContent = count + 1;

    imageContainer.appendChild(clone);
    imageTotalForms.value = count + 1;
});

imageContainer.addEventListener('click', e => {
    if (!e.target.classList.contains('remove-image')) return;
    const block = e.target.closest('.image-block');
    if (!block) return;

    const idInput = block.querySelector('input[name$="-id"]');
    if (idInput && idInput.value) {
        const deleteInput = block.querySelector('input[name$="-DELETE"]');
        if (deleteInput) deleteInput.checked = true;
        block.style.display = 'none';
    } else {
        block.remove();
    }
    renumberImages();
});

// Image file preview
imageContainer.addEventListener('change', e => {
    if (e.target.type !== 'file') return;
    const file = e.target.files[0];
    if (!file) return;
    const block = e.target.closest('.image-block');
    if (!block) return;
    const previewWrap = block.querySelector('.image-preview-wrap');
    const thumb = block.querySelector('.image-thumb');
    if (previewWrap && thumb) {
        const reader = new FileReader();
        reader.onload = ev => {
            thumb.src = ev.target.result;
            previewWrap.style.display = '';
        };
        reader.readAsDataURL(file);
    }
});


// ── Results Table ──────────────────────────────────────────────────────────

const resultsColHeaders = document.getElementById('results-col-headers');
const resultsTheadRow = document.getElementById('results-thead-row');
const resultsTbody = document.getElementById('results-tbody');
const resultsColumnsInput = document.getElementById('results-columns-input');
const resultsRowsInput = document.getElementById('results-rows-input');

let columns = [];  // array of column header strings

function renderResultsTable() {
    // Rebuild thead
    resultsTheadRow.innerHTML = '';
    columns.forEach((col, ci) => {
        const th = document.createElement('th');
        th.textContent = col;
        resultsTheadRow.appendChild(th);
    });
    // Add "Actions" th if we have columns
    if (columns.length) {
        const th = document.createElement('th');
        th.textContent = '';
        resultsTheadRow.appendChild(th);
    }

    // Rebuild each row's cells to match column count
    resultsTbody.querySelectorAll('tr').forEach(tr => {
        const cells = tr.querySelectorAll('td.result-cell');
        // Add missing cells
        for (let i = cells.length; i < columns.length; i++) {
            const td = document.createElement('td');
            td.className = 'result-cell';
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.className = 'result-cell-input';
            inp.placeholder = columns[i] || '';
            td.appendChild(inp);
            // Insert before the actions td
            const actionsTd = tr.querySelector('td.result-actions');
            tr.insertBefore(td, actionsTd);
        }
        // Remove excess cells
        const allCells = tr.querySelectorAll('td.result-cell');
        for (let i = columns.length; i < allCells.length; i++) {
            allCells[i].remove();
        }
        // Update placeholders
        tr.querySelectorAll('td.result-cell input').forEach((inp, ci) => {
            inp.placeholder = columns[ci] || '';
        });
    });
}

function addResultsRow(initialValues) {
    const tr = document.createElement('tr');
    columns.forEach((col, ci) => {
        const td = document.createElement('td');
        td.className = 'result-cell';
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'result-cell-input';
        inp.placeholder = col;
        inp.value = (initialValues && initialValues[ci]) ? initialValues[ci] : '';
        td.appendChild(inp);
        tr.appendChild(td);
    });
    // Actions cell
    const actionsTd = document.createElement('td');
    actionsTd.className = 'result-actions';
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-danger btn-sm';
    removeBtn.textContent = '×';
    removeBtn.addEventListener('click', () => tr.remove());
    actionsTd.appendChild(removeBtn);
    tr.appendChild(actionsTd);
    resultsTbody.appendChild(tr);
}

function addResultsColumn(headerValue) {
    const idx = columns.length;
    columns.push(headerValue || '');

    // Header input chip
    const wrap = document.createElement('div');
    wrap.className = 'col-header-wrap';
    wrap.dataset.colIndex = idx;

    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'col-header-input';
    inp.value = headerValue || '';
    inp.placeholder = `Column ${idx + 1}`;
    inp.addEventListener('input', () => {
        columns[parseInt(wrap.dataset.colIndex)] = inp.value;
        renderResultsTable();
    });

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-danger btn-sm col-remove-btn';
    removeBtn.textContent = '×';
    removeBtn.addEventListener('click', () => {
        const ci = parseInt(wrap.dataset.colIndex);
        columns.splice(ci, 1);
        wrap.remove();
        // Renumber remaining col wraps
        resultsColHeaders.querySelectorAll('.col-header-wrap').forEach((w, i) => {
            w.dataset.colIndex = i;
        });
        // Remove that column from all rows
        resultsTbody.querySelectorAll('tr').forEach(tr => {
            const cells = tr.querySelectorAll('td.result-cell');
            if (cells[ci]) cells[ci].remove();
        });
        renderResultsTable();
    });

    wrap.appendChild(inp);
    wrap.appendChild(removeBtn);
    resultsColHeaders.appendChild(wrap);

    // Add a cell to each existing row
    resultsTbody.querySelectorAll('tr').forEach(tr => {
        const td = document.createElement('td');
        td.className = 'result-cell';
        const cellInp = document.createElement('input');
        cellInp.type = 'text';
        cellInp.className = 'result-cell-input';
        cellInp.placeholder = headerValue || '';
        td.appendChild(cellInp);
        const actionsTd = tr.querySelector('td.result-actions');
        tr.insertBefore(td, actionsTd);
    });

    renderResultsTable();
}

document.getElementById('add-results-col').addEventListener('click', () => addResultsColumn(''));
document.getElementById('add-results-row').addEventListener('click', () => addResultsRow(null));

// Serialize results to hidden fields on form submit
document.querySelector('form').addEventListener('submit', () => {
    const cols = [];
    resultsColHeaders.querySelectorAll('.col-header-wrap').forEach(w => {
        cols.push(w.querySelector('.col-header-input').value);
    });
    const rows = [];
    resultsTbody.querySelectorAll('tr').forEach(tr => {
        const cells = [];
        tr.querySelectorAll('td.result-cell input').forEach(inp => cells.push(inp.value));
        rows.push(cells);
    });
    resultsColumnsInput.value = JSON.stringify(cols);
    resultsRowsInput.value = JSON.stringify(rows);
});

// Load initial data (for reports loaded from DB)
(function initResultsTable() {
    const scriptEl = document.getElementById('results-initial-data');
    if (!scriptEl) return;
    let data;
    try { data = JSON.parse(scriptEl.textContent); } catch { return; }
    if (!data.columns || !data.columns.length) return;

    data.columns.forEach(col => addResultsColumn(col));
    (data.rows || []).forEach(rowCells => addResultsRow(rowCells));
})();
