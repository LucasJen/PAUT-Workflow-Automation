// The weld form's equipment grid (reports/editor/_weld_grid.html, in the report editor and in
// Library › Defaults): probe and group columns are Django formset forms laid out column-wise. Adds, removes and duplicates columns, numbers them,
// lists the probe columns in each group's Probe select and greys the rows a probe kind leaves N/A.

(function () {
    const root = document.getElementById('weld-grids');
    if (!root) return;
    const rows = JSON.parse(document.getElementById('weld-grid-rows').textContent);
    const limits = { probes: rows.max_probes, groups: rows.max_groups };
    const grids = { probes: document.getElementById('probe-grid'), groups: document.getElementById('group-grid') };

    const totalInput = prefix => document.getElementById(`id_${prefix}-TOTAL_FORMS`);
    const field = (prefix, name) => document.getElementById(`id_${prefix}-${name}`);

    // Column prefixes ('probes-0', …) in page order, without the removed ones
    function columns(kind) {
        return Array.from(grids[kind].querySelectorAll('thead th[data-col]'))
            .filter(th => !th.hidden)
            .map(th => th.dataset.col);
    }

    function cells(kind, col) {
        return grids[kind].querySelectorAll(`[data-col="${CSS.escape(col)}"]`);
    }

    // ── Numbering, the groups' Probe options, Add limits ────────────────────

    function refresh() {
        for (const kind of ['probes', 'groups']) {
            const word = kind === 'probes' ? 'Probe' : 'Group';
            columns(kind).forEach((col, i) => {
                grids[kind].querySelector(`th[data-col="${CSS.escape(col)}"] .grid-col-number`).textContent = `${word} ${i + 1}`;
            });
            grids[kind].querySelector('[data-add-column]').disabled = columns(kind).length >= limits[kind];
        }
        // A group's Probe select keeps the probe form's index as its value; the text is the
        // probe's number on the page and model. Removed probes leave the list.
        const probes = columns('probes');
        root.querySelectorAll('select[name$="-probe_column"]').forEach(select => {
            const current = select.value;
            select.querySelectorAll('option').forEach(option => {
                if (option.value === '') return;
                const position = probes.indexOf(`probes-${option.value}`);
                option.hidden = position < 0;
                if (position >= 0) {
                    const model = field(`probes-${option.value}`, 'model')?.value.trim();
                    const label = field(`probes-${option.value}`, 'label')?.value.trim();
                    option.textContent = [`P${position + 1}`, label && `(${label})`, model && `· ${model}`].filter(Boolean).join(' ');
                }
            });
            if (current && select.selectedOptions[0]?.hidden) select.value = '';
        });
        applyKinds();
    }

    // ── Kind rules: N/A rows are greyed and read-only (the sheet prints N/A) ───

    function setNa(input, na) {
        if (!input || input.type === 'hidden') return;
        input.closest('td').classList.toggle('na', na);
        input.readOnly = na;
        input.tabIndex = na ? -1 : 0;
        if (na) {
            input.dataset.placeholder ??= input.placeholder;
            input.placeholder = 'N/A';
        } else if (input.dataset.placeholder !== undefined) {
            input.placeholder = input.dataset.placeholder;
        }
    }

    function probeKind(probeIndex) {
        return probeIndex === '' ? null : field(`probes-${probeIndex}`, 'kind')?.value || null;
    }

    function applyKinds() {
        for (const col of columns('probes')) {
            const na = new Set(rows.probe_na[field(col, 'kind').value] || []);
            rows.probe.forEach(([name]) => setNa(field(col, name), na.has(name)));
            // A wedge-less probe has no catalogue wedge either
            const wedge = field(col, 'catalogue_wedge');
            wedge.disabled = na.has('wedge_model');
            wedge.closest('td').classList.toggle('na', wedge.disabled);
        }
        for (const col of columns('groups')) {
            const na = new Set(rows.group_na[probeKind(field(col, 'probe_column').value)] || []);
            rows.group.forEach(([name]) => setNa(field(col, name), na.has(name)));
        }
    }

    // ── Add / remove / duplicate ─────────────────────────────────────────

    function addColumn(kind) {
        if (columns(kind).length >= limits[kind]) return null;
        const total = totalInput(kind);
        const index = Number(total.value);
        const html = document.getElementById(`${kind}-column-template`).innerHTML.replace(/__prefix__/g, String(index));
        // Parse the cells inside a row so the browser keeps <th>/<td>
        const scratch = document.createElement('tbody');
        scratch.innerHTML = `<tr>${html}</tr>`;
        for (const cell of Array.from(scratch.firstElementChild.children)) {
            const tr = grids[kind].querySelector(`tr[data-row="${cell.dataset.row}"]`);
            tr.insertBefore(cell, tr.lastElementChild);   // before the Add column
        }
        total.value = String(index + 1);
        const col = `${kind}-${index}`;
        if (kind === 'groups') {
            // A new group uses the last probe column
            const probes = columns('probes');
            if (probes.length) field(col, 'probe_column').value = probes[probes.length - 1].split('-')[1];
        }
        refresh();
        return col;
    }

    function removeColumn(kind, col) {
        // Tick DELETE and hide it: the save removes a saved column and skips a new one
        field(col, 'DELETE').checked = true;
        cells(kind, col).forEach(cell => { cell.hidden = true; });
        refresh();
    }

    async function duplicateColumn(kind, col) {
        const copy = addColumn(kind);
        if (!copy) return;
        cells(kind, col).forEach(cell => {
            cell.querySelectorAll('input:not([type=hidden]):not([type=checkbox]), select, textarea, input[type=hidden][name*="-wedge_"]').forEach(input => {
                const name = input.name.slice(col.length + 1);
                const target = field(copy, name);
                if (!target || name === 'catalogue_wedge') return;
                target.value = input.value;
            });
        });
        if (kind === 'probes' && window.CatalogueSelect) {
            await window.CatalogueSelect.setPair(field(copy, 'catalogue_probe'),
                field(col, 'catalogue_probe').value || null, field(col, 'catalogue_wedge').value || null);
        }
        refresh();
        root.closest('form')?.dispatchEvent(new Event('input', { bubbles: true }));
    }

    root.addEventListener('click', event => {
        const add = event.target.closest('[data-add-column]');
        const remove = event.target.closest('[data-remove-column]');
        const duplicate = event.target.closest('[data-duplicate-column]');
        if (!add && !remove && !duplicate) return;
        const table = event.target.closest('table');
        const kind = table.dataset.prefix;
        const markDirty = () => table.dispatchEvent(new Event('input', { bubbles: true }));
        if (add) {
            const col = addColumn(kind);
            if (col) field(col, 'label').focus();
        } else {
            const col = event.target.closest('th[data-col]').dataset.col;
            if (remove) removeColumn(kind, col);
            else duplicateColumn(kind, col);
        }
        markDirty();
    });

    // Kind, probe choice, label and model changes renumber / re-grey
    root.addEventListener('change', event => {
        if (/-(kind|probe_column|label|model)$/.test(event.target.name || '')) refresh();
    });
    root.addEventListener('input', event => {
        if (/^probes-\d+-(label|model)$/.test(event.target.name || '')) refresh();
    });

    // ── Filling columns ──────────────────────────────────────────────────

    async function fillColumn(col, values, { keepLabel = false } = {}) {
        for (const [name, value] of Object.entries(values)) {
            if (name === 'catalogue_probe' || name === 'catalogue_wedge' || name === 'probe_column') continue;
            const input = field(col, name);
            if (!input || value === null || value === undefined) continue;
            if (name === 'label' && keepLabel && input.value.trim()) continue;
            input.value = value;
        }
        if (values.catalogue_probe && window.CatalogueSelect) {
            await window.CatalogueSelect.setPair(field(col, 'catalogue_probe'), values.catalogue_probe, values.catalogue_wedge || null);
        }
    }

    // ── A new report starts with its type's prefilled columns (Library › Defaults) ─────
    // Columns made from defaults and not yet edited are swapped when the report type changes.

    const typeSelect = document.getElementById('id_report_type');
    const reportId = document.querySelector('input[name="report_id"]');
    const pristine = new Set();

    function typeDefaults(type) {
        try {
            return JSON.parse(document.getElementById('report-defaults').textContent)[type] || {};
        } catch (e) {
            return {};
        }
    }

    async function addDefaultColumns(type) {
        const { probes = [], groups = [] } = typeDefaults(type);
        const placed = {};
        for (const [i, values] of probes.entries()) {
            const col = addColumn('probes');
            if (!col) break;
            await fillColumn(col, values);
            placed[String(i)] = col;
            pristine.add(col);
        }
        for (const values of groups) {
            const col = addColumn('groups');
            if (!col) break;
            await fillColumn(col, values);
            const probe = placed[values.probe_column];
            field(col, 'probe_column').value = probe ? probe.split('-')[1] : '';
            pristine.add(col);
        }
        refresh();
    }

    if (typeSelect && reportId) {
        // Editing a cell makes its column the user's own
        ['input', 'change'].forEach(type => root.addEventListener(type, event => {
            const col = event.target.closest('[data-col]')?.dataset.col;
            if (col) pristine.delete(col);
        }));
        const empty = () => !columns('probes').length && !columns('groups').length;
        if (!reportId.value && empty()) addDefaultColumns(typeSelect.value);
        typeSelect.addEventListener('change', async () => {
            for (const col of pristine) removeColumn(col.split('-')[0], col);
            pristine.clear();
            if (empty()) await addDefaultColumns(typeSelect.value);
        });
    }

    // ── Import: .nde groups and saved setups fill columns ──────────────────
    // Each item is {instrument, probe, group, probe_key} (reports/weld_columns.py). A probe
    // already on the page (same model and S/N) is reused, so several groups share its column.
    // Otherwise the first column of the same kind that no file has filled yet (e.g. one
    // prefilled from the defaults) is filled, keeping its values where the file has none; a new
    // column is added only when there's none left.

    const toolbar = document.getElementById('weld-grid-toolbar');
    const status = document.getElementById('weld-grid-status');

    function showStatus(text, isError = false) {
        if (!status) return;
        status.textContent = text;
        status.classList.toggle('text-danger', isError);
    }

    function pageProbeKey(col) {
        const model = field(col, 'model').value.trim().toLowerCase();
        return model ? `${model}|${field(col, 'serial').value.trim().toLowerCase()}` : '';
    }

    const fillable = col => Boolean(field(col, 'source_file')) && !field(col, 'source_file').value;
    const probeIndex = col => col.split('-')[1];

    function groupProbeKind(col) {
        const probe = field(col, 'probe_column').value;
        return probe === '' ? null : field(`probes-${probe}`, 'kind')?.value;
    }

    async function importColumns(items) {
        const counts = { filled: 0, added: 0, skipped: 0 };
        for (const item of items) {
            const kind = item.probe.kind || 'paut';
            // The instrument: fill only what's still blank
            for (const [name, value] of Object.entries(item.instrument || {})) {
                const input = document.getElementById(`id_${name}`);
                if (input && !input.value.trim()) input.value = value;
            }

            let probeCol = item.probe_key ? columns('probes').find(col => pageProbeKey(col) === item.probe_key) : null;
            if (!probeCol) {
                probeCol = columns('probes').find(col => fillable(col) && field(col, 'kind').value === kind);
                if (probeCol) counts.filled += 1;
                else if ((probeCol = addColumn('probes'))) counts.added += 1;
                else { counts.skipped += 1; continue; }
                await fillColumn(probeCol, item.probe, { keepLabel: true });
            }

            // A group column still waiting for a file: one on this probe first, then one on an
            // unfilled probe of the same kind
            const waiting = columns('groups').filter(fillable);
            let groupCol = waiting.find(col => field(col, 'probe_column').value === probeIndex(probeCol))
                || waiting.find(col => groupProbeKind(col) === kind && fillable(`probes-${field(col, 'probe_column').value}`));
            if (groupCol) counts.filled += 1;
            else if ((groupCol = addColumn('groups'))) counts.added += 1;
            else { counts.skipped += 1; continue; }
            await fillColumn(groupCol, { label: item.label || '', ...item.group }, { keepLabel: true });
            field(groupCol, 'probe_column').value = probeIndex(probeCol);
            pristine.delete(probeCol);
            pristine.delete(groupCol);
        }
        refresh();
        root.closest('form')?.dispatchEvent(new Event('input', { bubbles: true }));
        const parts = [];
        if (counts.filled) parts.push(`filled ${counts.filled} prefilled column${counts.filled === 1 ? '' : 's'}`);
        if (counts.added) parts.push(`added ${counts.added} column${counts.added === 1 ? '' : 's'}`);
        if (counts.skipped) parts.push(`${counts.skipped} left out: the form holds ${limits.probes} probes and ${limits.groups} groups`);
        const text = parts.join('; ') || 'nothing to add';
        showStatus(text[0].toUpperCase() + text.slice(1) + '.', counts.skipped > 0);
    }

    if (toolbar) {
        const ndeFile = document.getElementById('weld-nde-file');
        document.getElementById('weld-nde-import').addEventListener('click', () => ndeFile.click());
        ndeFile.addEventListener('change', async event => {
            event.stopPropagation();   // choosing a file isn't a change to the report itself
            const file = ndeFile.files[0];
            ndeFile.value = '';
            if (!file) return;
            const body = new FormData();
            body.append('nde_file', file);
            body.append('units', document.getElementById('weld-nde-units').value);
            body.append('csrfmiddlewaretoken', root.closest('form').querySelector('[name=csrfmiddlewaretoken]').value);
            showStatus(`Reading ${file.name}…`);
            try {
                const response = await fetch(toolbar.dataset.ndeUrl, { method: 'POST', body });
                const data = await response.json();
                if (data.error) showStatus(data.error, true);
                else await importColumns(data.columns);
            } catch (error) {
                showStatus(`Couldn't read ${file.name}.`, true);
            }
        });

        const savedColumns = JSON.parse(document.getElementById('saved-setup-columns').textContent);
        const setupLoader = document.getElementById('weld-setup-loader');
        setupLoader.addEventListener('change', async event => {
            event.stopPropagation();
            const item = savedColumns[setupLoader.value];
            setupLoader.value = '';
            if (item) await importColumns([item]);
        });
        // The toolbar's controls aren't part of the report (no unsaved-changes from them)
        ['input', 'change'].forEach(type => toolbar.addEventListener(type, event => event.stopPropagation()));
    }

    // ── Keyboard: arrows move between cells, Ctrl+Shift+→ fills right ────────

    function cellInput(td) {
        return td?.querySelector('input:not([type=hidden]):not([type=checkbox]), select, textarea');
    }

    function visibleCells(tr) {
        return Array.from(tr.children).filter(cell => !cell.hidden && cell.tagName === 'TD' && cellInput(cell));
    }

    root.addEventListener('keydown', event => {
        const input = event.target;
        const td = input.closest('td');
        if (!td || !td.dataset.col && !td.closest('.instrument-grid')) return;
        const tr = td.parentElement;

        if (event.key === 'ArrowRight' && event.ctrlKey && event.shiftKey) {
            // Fill right: this value into the same row of every later column
            event.preventDefault();
            const row = visibleCells(tr);
            row.slice(row.indexOf(td) + 1).forEach(cell => {
                const target = cellInput(cell);
                if (target && !target.readOnly && !target.disabled && target.tagName === input.tagName) {
                    target.value = input.value;
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
            input.dispatchEvent(new Event('input', { bubbles: true }));
            return;
        }

        if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
        let target = null;
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            if (input.tagName === 'SELECT') return;   // arrows choose an option
            const column = Array.from(tr.children).indexOf(td);
            let next = event.key === 'ArrowUp' ? tr.previousElementSibling : tr.nextElementSibling;
            while (next && !(target = cellInput(next.children[column]))) {
                next = event.key === 'ArrowUp' ? next.previousElementSibling : next.nextElementSibling;
            }
        } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && input.tagName !== 'SELECT') {
            // Only leave the cell when the caret is at its edge
            const atStart = input.selectionStart === 0 && input.selectionEnd === 0;
            const atEnd = input.selectionStart === input.value.length;
            if (event.key === 'ArrowLeft' ? !atStart : !atEnd) return;
            const row = visibleCells(tr);
            target = cellInput(row[row.indexOf(td) + (event.key === 'ArrowLeft' ? -1 : 1)]);
        }
        if (target) {
            event.preventDefault();
            target.focus();
            target.select?.();
        }
    });

    // A page re-shown after a failed save keeps the columns removed before it hidden
    for (const kind of ['probes', 'groups']) {
        grids[kind].querySelectorAll('thead th[data-col]').forEach(th => {
            if (field(th.dataset.col, 'DELETE')?.checked) cells(kind, th.dataset.col).forEach(cell => { cell.hidden = true; });
        });
    }
    refresh();
})();
