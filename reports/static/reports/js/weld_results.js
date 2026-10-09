// The weld form's results (reports/editor/weld_results.html): a block per weld with its
// indications under it. On save it writes the weld form's rows into the results inputs (the
// same rows the Excel output reads): a weld's first indication shares the weld's row, each
// further indication gets a row with a blank Weld ID, and a weld with no indications is one row
// carrying its own Accept / Reject and notes.

(function () {
    const root = document.getElementById('weld-results');
    if (!root) return;
    const section = root.closest('.editor-section');
    const form = root.closest('form');
    const list = document.getElementById('weld-results-list');
    const readJson = (id, fallback) => {
        try { return JSON.parse(document.getElementById(id).textContent); } catch (e) { return fallback; }
    };

    const columns = readJson('report-types', {}).paut_weld?.results_columns || [];
    const keys = columns.map(c => c.key);
    const heading = Object.fromEntries(columns.map(c => [c.key, c.heading]));
    const split = keys.indexOf('circ_start');
    const WELD = keys.slice(0, split);         // Weld ID … Probe 2 Thickness
    const INDICATION = keys.slice(split);      // Circ Start … Notes / Comments
    const VERDICT = ['accept', 'comments'];    // what a weld without indications still records
    // What a new weld starts with from the one before it (usually the same pipe)
    const CARRIED = ['cl_offset', 'weld_width', 'probe1_location', 'probe1_thk', 'probe2_thk'];
    const maxRows = Number(root.dataset.maxRows);
    // Indication images saved so far: {indication key: url}. A key ties an image to its
    // indication; it's saved as one extra cell after the row's Notes / Comments.
    const savedImages = readJson('indication-images', {});
    const KEY_INDEX = keys.length;
    const newKey = () => 'ind-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const pageRows = Number(root.dataset.pageRows);

    const markDirty = () => form.dispatchEvent(new Event('input', { bubbles: true }));
    // A weld scanned at more than one index offset: its C/L Offset cell holds each ('0.500 / 0.875')
    const OFFSET = 'cl_offset';
    const OFFSET_JOIN = ' / ';

    // ── Cells ─────────────────────────────────────────────────────────────

    function verdictText(value) {
        const v = (value || '').trim().toLowerCase();
        if (/^(a|p|✓)/.test(v)) return 'Accept';
        if (/^(r|f|x|☓)/.test(v)) return 'Reject';
        return value || '';
    }

    function textInput(key, value) {
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control form-control-sm';
        input.value = value;
        input.dataset.key = key;
        input.dataset.fill = 'user';   // typed in (fill_marks.js outlines it while empty)
        input.setAttribute('aria-label', heading[key]);
        return input;
    }

    // The C/L Offset cell: an input per offset, + for another (each extra one with ✕ to drop it)
    function offsetCell(value = '') {
        const td = document.createElement('td');
        const list = document.createElement('div');
        list.className = 'offset-list';
        const add = document.createElement('button');
        add.type = 'button';
        add.className = 'btn btn-link btn-sm offset-add';
        add.dataset.addOffset = '';
        add.title = "Another index offset this weld was scanned at (then press Scan plan to add it to the drawings)";
        add.innerHTML = '<i class="bi bi-plus-lg"></i> Offset';
        td.append(list, add);
        const offsets = value.split('/').map(v => v.trim()).filter(Boolean);
        (offsets.length ? offsets : ['']).forEach(v => addOffset(td, v));
        return td;
    }

    function addOffset(td, value = '') {
        const list = td.querySelector('.offset-list');
        const input = textInput(OFFSET, value);
        if (!list.children.length) {
            list.append(input);
            return input;
        }
        input.setAttribute('aria-label', `${heading[OFFSET]} ${list.children.length + 1}`);
        delete input.dataset.fill;   // an extra offset may be left empty
        const row = document.createElement('div');
        row.className = 'offset-extra';
        const drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'btn btn-icon btn-sm';
        drop.dataset.removeOffset = '';
        drop.title = 'Remove this offset';
        drop.innerHTML = '<i class="bi bi-x"></i>';
        row.append(input, drop);
        list.append(row);
        return input;
    }

    function cell(key, value = '') {
        if (key === OFFSET) return offsetCell(value);
        const td = document.createElement('td');
        let input;
        if (key === 'accept') {
            input = document.createElement('select');
            input.className = 'form-select form-select-sm';
            const verdict = verdictText(value);
            for (const option of ['', 'Accept', 'Reject', ...(['', 'Accept', 'Reject'].includes(verdict) ? [] : [verdict])]) {
                input.add(new Option(option || '—', option));
            }
            input.value = verdict;
            input.dataset.key = key;
            input.dataset.fill = 'user';
            input.setAttribute('aria-label', heading[key]);
        } else {
            input = textInput(key, value);
        }
        td.append(input);
        return td;
    }

    function headRow(fieldKeys, actions = '') {
        const tr = document.createElement('tr');
        for (const key of fieldKeys) {
            const th = document.createElement('th');
            th.scope = 'col';
            th.textContent = heading[key];
            tr.append(th);
        }
        const th = document.createElement('th');
        th.className = 'results-actions';
        th.innerHTML = actions;
        tr.append(th);
        return tr;
    }

    const value = (scope, key) => key === OFFSET
        ? Array.from(scope.querySelectorAll(`[data-key="${OFFSET}"]`), i => i.value.trim()).filter(Boolean).join(OFFSET_JOIN)
        : scope.querySelector(`[data-key="${key}"]`)?.value.trim() || '';

    // ── Welds and indications ───────────────────────────────────────────────

    function addWeld(values = {}) {
        const block = document.createElement('div');
        block.className = 'weld-block weld-grid-wrap';
        block.innerHTML = `
            <table class="weld-grid results-grid"><thead></thead><tbody><tr class="weld-row"></tr></tbody></table>
            <p class="weld-status" role="status" hidden></p>
            <table class="weld-grid results-grid weld-verdict"><tbody><tr></tr></tbody></table>
            <table class="weld-grid results-grid indications" hidden><thead></thead><tbody></tbody></table>`;
        const [weldTable, verdictTable, indicationTable] = block.querySelectorAll('table');
        weldTable.tHead.append(headRow(WELD, `
            <button type="button" class="btn btn-secondary btn-sm" data-weld-scan-plan title="Add this weld's offset and skews to the report's scan plan"><i class="bi bi-rulers"></i> Scan plan</button>
            <button type="button" class="btn btn-secondary btn-sm" data-add-indication><i class="bi bi-plus-lg"></i> Add indication</button>
            <button type="button" class="btn btn-icon btn-sm" data-remove-weld title="Remove this weld"><i class="bi bi-x-lg"></i></button>`));
        const row = weldTable.querySelector('.weld-row');
        WELD.forEach(key => row.append(cell(key, values[key])));
        row.append(document.createElement('td'));

        // Accept / Reject and notes of a weld with no indications ("No rejectable indications…")
        const verdict = verdictTable.querySelector('tr');
        for (const key of VERDICT) {
            const th = document.createElement('th');
            th.scope = 'row';
            th.textContent = heading[key];
            verdict.append(th, cell(key, values[key]));
        }
        const indicationHead = headRow(INDICATION);
        const imageHead = document.createElement('th');
        imageHead.className = 'results-image';
        imageHead.textContent = 'Image';
        imageHead.title = 'Optional: an indication with an image gets its own Indication page';
        indicationHead.insertBefore(imageHead, indicationHead.lastElementChild);
        indicationTable.tHead.append(indicationHead);
        list.append(block);
        refresh();
        return block;
    }

    function addIndication(block, values = {}) {
        const body = block.querySelector('.indications tbody');
        // The first indication takes over the weld's own verdict and notes
        if (!body.rows.length) {
            const verdict = block.querySelector('.weld-verdict');
            values = { accept: value(verdict, 'accept'), comments: value(verdict, 'comments'), ...values };
        }
        const tr = document.createElement('tr');
        tr.dataset.key = values.key || newKey();
        INDICATION.forEach(key => tr.append(cell(key, values[key])));
        tr.append(imageCell(tr.dataset.key));
        const actions = document.createElement('td');
        actions.className = 'results-actions';
        actions.innerHTML = '<button type="button" class="btn btn-icon btn-sm" data-remove-indication title="Remove this indication"><i class="bi bi-x-lg"></i></button>';
        tr.append(actions);
        body.append(tr);
        refresh();
        return tr;
    }

    // An indication's optional image: a file input saved with the report, shown as its thumbnail
    // (with ✕ to remove it) once saved, or as the chosen file's name before
    function imageCell(key) {
        const td = document.createElement('td');
        td.className = 'results-image';
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.name = `indication_image_${key}`;
        input.hidden = true;
        const pick = document.createElement('button');
        pick.type = 'button';
        pick.className = 'btn btn-icon btn-sm';
        pick.title = 'Add an image (gives this indication its Indication page)';
        pick.innerHTML = '<i class="bi bi-image"></i>';
        const shown = document.createElement('span');
        shown.className = 'results-image-shown';
        const remove = document.createElement('input');
        remove.type = 'checkbox';
        remove.name = 'remove_indication_image';
        remove.value = key;
        remove.hidden = true;

        function show() {
            shown.replaceChildren();
            if (input.files.length) {
                shown.textContent = input.files[0].name;
                shown.title = 'Saved with the report';
            } else if (savedImages[key] && !remove.checked) {
                const link = document.createElement('a');
                link.href = savedImages[key];
                link.target = '_blank';
                const img = document.createElement('img');
                img.src = savedImages[key];
                img.alt = 'Indication image';
                link.append(img);
                const drop = document.createElement('button');
                drop.type = 'button';
                drop.className = 'btn btn-icon btn-sm';
                drop.title = 'Remove this image (no Indication page)';
                drop.innerHTML = '<i class="bi bi-x"></i>';
                drop.addEventListener('click', () => { remove.checked = true; show(); markChanged(); });
                shown.append(link, drop);
            }
            pick.hidden = Boolean(input.files.length) || (Boolean(savedImages[key]) && !remove.checked);
        }
        pick.addEventListener('click', () => input.click());
        input.addEventListener('change', () => { remove.checked = false; show(); });
        td.append(input, remove, pick, shown);
        show();
        return td;
    }

    function markChanged() {
        form.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function removeIndication(tr) {
        const block = tr.closest('.weld-block');
        const body = tr.parentElement;
        // The last one hands its verdict and notes back to the weld
        if (body.rows.length === 1) {
            const verdict = block.querySelector('.weld-verdict');
            for (const key of VERDICT) verdict.querySelector(`[data-key="${key}"]`).value = verdictText(value(tr, key)) || value(tr, key);
        }
        tr.remove();
        refresh();
    }

    // ── Rows: the weld form's results rows, in WELD_RESULTS_COLUMNS order ─────

    function rows() {
        const out = [];
        for (const block of list.querySelectorAll('.weld-block')) {
            const weld = WELD.map(key => value(block.querySelector('.weld-row'), key));
            const indications = Array.from(block.querySelectorAll('.indications tbody tr'));
            if (!indications.length) {
                const verdict = block.querySelector('.weld-verdict');
                const row = [...weld, ...INDICATION.map(key => VERDICT.includes(key) ? value(verdict, key) : '')];
                if (row.some(Boolean)) out.push(row);
                continue;
            }
            indications.forEach((tr, i) => {
                out.push([...(i === 0 ? weld : weld.map(() => '')), ...INDICATION.map(key => value(tr, key)), tr.dataset.key]);
            });
        }
        return out;
    }

    function refresh() {
        const blocks = list.querySelectorAll('.weld-block');
        document.getElementById('weld-results-empty').hidden = blocks.length > 0;
        for (const block of blocks) {
            const count = block.querySelectorAll('.indications tbody tr').length;
            block.querySelector('.indications').hidden = count === 0;
            block.querySelector('.weld-verdict').hidden = count > 0;
        }
        const used = rows().length;
        const counter = document.getElementById('weld-results-count');
        counter.textContent = used
            ? `${used} of ${maxRows} rows used (${pageRows} fit on page 1, the rest go on the Continuation page).`
            : '';
        counter.classList.toggle('text-danger', used > maxRows);
        if (used > maxRows) counter.textContent += ` The form only holds ${maxRows}; the rest won't print.`;
    }

    // ── Loading the saved rows ─────────────────────────────────────────────

    function load() {
        const data = readJson('results-initial-data', {});
        const index = Object.fromEntries(keys.map(key => [key, (data.columns || []).indexOf(heading[key])]));
        if (!Object.values(index).some(i => i >= 0)) return;   // not a weld report's table
        let block = null;
        for (const row of data.rows || []) {
            const values = Object.fromEntries(keys.map(key => [key, index[key] >= 0 ? (row[index[key]] || '') : '']));
            const indication = { ...Object.fromEntries(INDICATION.map(key => [key, values[key]])), key: row[KEY_INDEX] || '' };
            const hasFlaw = INDICATION.some(key => !VERDICT.includes(key) && values[key].trim());
            if (values.weld_id.trim() || !block) {
                block = addWeld(hasFlaw ? Object.fromEntries(WELD.map(key => [key, values[key]])) : values);
                if (hasFlaw) addIndication(block, indication);
            } else {
                addIndication(block, indication);
            }
        }
    }

    // ── Scan plan from a weld: thickness, width, C/L offset and skews into the report's plan ──

    async function addToScanPlan(block) {
        const status = block.querySelector('.weld-status');
        const weld = block.querySelector('.weld-row');
        const body = new FormData();
        body.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
        body.append('report_id', form.querySelector('[name=report_id]').value);
        for (const key of ['cl_offset', 'weld_width', 'probe1_location', 'probe1_thk']) body.append(key, value(weld, key));
        status.hidden = false;
        status.classList.remove('text-danger');
        status.textContent = 'Updating the scan plan…';
        try {
            const response = await fetch(root.dataset.scanPlanUrl, { method: 'POST', body });
            const data = await response.json();
            status.textContent = data.message;
            status.classList.toggle('text-danger', !data.ok);
            if (data.plan) {
                const link = document.createElement('a');
                link.href = data.plan.url;
                link.target = '_blank';
                link.textContent = 'Open scan plan';
                status.append(' ', link);
                // The report's Scan plan select shows the plan (its next save keeps it)
                const select = document.getElementById('id_scan_plan');
                if (select) {
                    if (![...select.options].some(o => o.value === String(data.plan.pk))) {
                        select.add(new Option(data.plan.name, data.plan.pk));
                    }
                    select.value = String(data.plan.pk);
                }
            }
        } catch (error) {
            status.textContent = "Couldn't reach the scan plan.";
            status.classList.add('text-danger');
        }
    }

    // ── Events ────────────────────────────────────────────────────────────

    document.getElementById('add-weld').addEventListener('click', () => {
        const blocks = list.querySelectorAll('.weld-block');
        const last = blocks[blocks.length - 1];
        const carried = last ? Object.fromEntries(CARRIED.map(key => [key, value(last.querySelector('.weld-row'), key)])) : {};
        const block = addWeld(carried);
        block.querySelector('[data-key="weld_id"]').focus();
        markDirty();
    });

    list.addEventListener('click', event => {
        const block = event.target.closest('.weld-block');
        if (event.target.closest('[data-weld-scan-plan]')) {
            addToScanPlan(block);
            return;   // changes the scan plan, not the report
        }
        if (event.target.closest('[data-add-offset]')) {
            addOffset(event.target.closest('td')).focus();
        } else if (event.target.closest('[data-remove-offset]')) {
            event.target.closest('.offset-extra').remove();
        } else if (event.target.closest('[data-add-indication]')) {
            addIndication(block).querySelector('input, select').focus();
        } else if (event.target.closest('[data-remove-indication]')) {
            removeIndication(event.target.closest('tr'));
        } else if (event.target.closest('[data-remove-weld]')) {
            block.remove();
            refresh();
        } else {
            return;
        }
        markDirty();
    });
    list.addEventListener('input', refresh);
    list.addEventListener('change', refresh);

    // Saving a weld report: these rows are its results (the long form's table is hidden)
    form.addEventListener('submit', () => {
        if (section.hidden) return;
        document.getElementById('results-columns-input').value = JSON.stringify(columns.map(c => c.heading));
        document.getElementById('results-rows-input').value = JSON.stringify(rows());
    });

    load();
})();
