// The weld form's equipment grid (reports/editor/_weld_grid.html, in the report editor and in
// Library › Defaults): probe and group columns are Django formset forms laid out column-wise. Adds, removes and duplicates columns, numbers them,
// lists the probe columns in each group's Probe select and greys the rows a probe kind leaves N/A.

(function () {
    const root = document.getElementById('weld-grids');
    if (!root) return;
    const rows = JSON.parse(document.getElementById('weld-grid-rows').textContent);
    const limits = { probes: rows.max_probes, groups: rows.max_groups };
    const grids = { probes: document.getElementById('probe-grid'), groups: document.getElementById('group-grid') };

    const NOT_USED = 'na';   // weld_form.NOT_USED: the N/A kind / Probe choice

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
            const cols = columns(kind);
            cols.forEach((col, i) => {
                const head = grids[kind].querySelector(`th[data-col="${CSS.escape(col)}"]`);
                head.querySelector('.grid-col-number').textContent = `${word} ${i + 1}`;
                head.querySelector('[data-move-column="-1"]').disabled = i === 0;
                head.querySelector('[data-move-column="1"]').disabled = i === cols.length - 1;
                // The column's place on the page is what the save orders by
                field(col, 'ORDER').value = String(i + 1);
            });
            grids[kind].querySelector('[data-add-column]').disabled = columns(kind).length >= limits[kind];
        }
        // A group's Probe select keeps the probe form's index as its value; the text is the
        // probe's number on the page and model. Removed probes leave the list.
        const probes = columns('probes');
        root.querySelectorAll('select[name$="-probe_column"]').forEach(select => {
            const current = select.value;
            select.querySelectorAll('option').forEach(option => {
                if (option.value === '' || option.value === NOT_USED) return;
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

    // A group's kind: its probe's, or N/A when the group itself is set to N/A
    function probeKind(probeIndex) {
        if (probeIndex === NOT_USED) return NOT_USED;
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
            // An N/A probe has no catalogue probe either
            const probe = field(col, 'catalogue_probe');
            probe.disabled = na.has('model');
            probe.closest('td').classList.toggle('na', probe.disabled);
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

    // Moves a column's cells, row by row, in front of another column's (or to the end, before
    // the Add column, when `before` is null)
    function placeBefore(kind, col, before) {
        for (const tr of grids[kind].querySelectorAll('tr')) {
            const cell = tr.querySelector(`:scope > [data-col="${CSS.escape(col)}"]`);
            if (!cell) continue;
            const target = before ? tr.querySelector(`:scope > [data-col="${CSS.escape(before)}"]`) : tr.lastElementChild;
            tr.insertBefore(cell, target);
        }
    }

    function moveColumn(kind, col, step) {
        const cols = columns(kind);
        const i = cols.indexOf(col);
        const j = i + step;
        if (i < 0 || j < 0 || j >= cols.length) return;
        if (step < 0) placeBefore(kind, col, cols[j]);
        else placeBefore(kind, cols[j], col);
        refresh();
        grids[kind].querySelector(`th[data-col="${CSS.escape(col)}"] [data-move-column="${step}"]:not(:disabled)`)?.focus();
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
        // The copy goes right after its original
        const cols = columns(kind);
        const next = cols[cols.indexOf(col) + 1];
        if (next && next !== copy) placeBefore(kind, copy, next);
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
        const move = event.target.closest('[data-move-column]');
        if (!add && !remove && !duplicate && !move) return;
        const table = event.target.closest('table');
        const kind = table.dataset.prefix;
        const markDirty = () => table.dispatchEvent(new Event('input', { bubbles: true }));
        if (add) {
            const col = addColumn(kind);
            // A probe column starts at its label; a group column (headed Group n) at its first cell
            if (col) (field(col, 'label') || cells(kind, col)[1]?.querySelector('input, select'))?.focus();
        } else {
            const col = event.target.closest('th[data-col]').dataset.col;
            if (remove) removeColumn(kind, col);
            else if (move) moveColumn(kind, col, Number(move.dataset.moveColumn));
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
            field(col, 'probe_column').value = values.probe_column === NOT_USED ? NOT_USED : probe ? probe.split('-')[1] : '';
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
        // "Reload defaults" (create_report.js): the default columns, when the grid has none
        window.WeldGrid = {
            async reloadDefaultColumns() {
                if (!empty()) return false;
                await addDefaultColumns(typeSelect.value);
                return true;
            },
        };
        typeSelect.addEventListener('change', async () => {
            for (const col of pristine) removeColumn(col.split('-')[0], col);
            pristine.clear();
            if (empty()) await addDefaultColumns(typeSelect.value);
        });
    }

    // ── Import: .nde groups and saved setups fill columns ──────────────────
    // Each item is {instrument, probe, group, probe_key, probe_ref, filename} (reports/weld_columns.py,
    // views/nde.py nde_columns): one per group of the file. importColumns says where each goes.

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
        return probeKind(field(col, 'probe_column').value);
    }

    // One import fills every probe and group of the file. Where each goes:
    // - a group: the column that came from the same file and group (importing again updates it;
    //   older imports remembered only the file), else the first column of the same kind no file
    //   has filled yet, else a new column;
    // - a probe: the column the file's earlier groups put it in (same probe in the file), else
    //   the column with the same model and S/N, else as a group. The file's values replace what's
    //   there; values the file doesn't have (cable, probe check, labels...) stay.
    // Calibration times from the scans' times: Initial 15 min before the earliest scan (down to
    // 5 min), Cal. out 15 min after the latest (up to 5 min), as 24 h text ('0705'). Each import
    // widens the window; the checks stay as typed.
    function calibrationTimes(scanTimes) {
        const minutes = scanTimes.map(t => (t.match(/(\d{2}):(\d{2})/) || []).slice(1).map(Number))
            .filter(hm => hm.length === 2).map(([h, m]) => h * 60 + m);
        if (!minutes.length) return;
        const text = m => String(Math.floor(m / 60) % 24).padStart(2, '0') + String(m % 60).padStart(2, '0');
        const read = el => { const t = (el?.value || '').match(/^(\d{1,2}):?(\d{2})$/); return t ? +t[1] * 60 + +t[2] : null; };
        const initial = document.getElementById('id_cal_time_initial');
        const out = document.getElementById('id_cal_time_out');
        const start = Math.max(0, Math.floor((Math.min(...minutes) - 15) / 5) * 5);
        const end = Math.min(24 * 60 - 1, Math.ceil((Math.max(...minutes) + 15) / 5) * 5);
        if (initial && (read(initial) === null || start < read(initial))) initial.value = text(start);
        if (out && (read(out) === null || end > read(out))) out.value = text(end);
    }

    async function importColumns(items) {
        const counts = { updated: 0, filled: 0, added: 0, skipped: 0 };
        const scopes = new Set();   // instruments found in the scope library
        const placed = {};          // probe_ref -> probe column, within this import
        const claimed = new Set();  // group columns this import has used
        const source = col => field(col, 'source_file')?.value || '';
        for (const item of items) {
            const kind = item.probe.kind || 'paut';
            // The instrument: the file's, with what the scope library knows by S/N (cal due,
            // module, scanner type, analysis software); what neither has stays as typed
            for (const [name, value] of Object.entries(item.instrument || {})) {
                const input = document.getElementById(`id_${name}`);
                if (input) input.value = value;
            }
            if (item.scope) scopes.add(item.scope);

            let probeCol = (item.probe_ref && placed[item.probe_ref])
                || (item.probe_key ? columns('probes').find(col => pageProbeKey(col) === item.probe_key) : null);
            if (probeCol) {
                if (!Object.values(placed).includes(probeCol)) counts.updated += 1;
            } else {
                probeCol = columns('probes').find(col => fillable(col) && field(col, 'kind').value === kind);
                if (probeCol) counts.filled += 1;
                else if ((probeCol = addColumn('probes'))) counts.added += 1;
                else { counts.skipped += 1; continue; }
            }
            if (!Object.values(placed).includes(probeCol)) await fillColumn(probeCol, item.probe, { keepLabel: true });
            if (item.probe_ref) placed[item.probe_ref] = probeCol;

            const open = columns('groups').filter(col => !claimed.has(col));
            let groupCol = open.find(col => source(col) && source(col) === item.group.source_file)
                || (item.filename && open.find(col => source(col) === item.filename));
            if (groupCol) {
                counts.updated += 1;
            } else {
                // A group column still waiting for a file: one on this probe first, then one on an
                // unfilled probe of the same kind
                const waiting = open.filter(fillable);
                groupCol = waiting.find(col => field(col, 'probe_column').value === probeIndex(probeCol))
                    || waiting.find(col => groupProbeKind(col) === kind && fillable(`probes-${field(col, 'probe_column').value}`));
                if (groupCol) counts.filled += 1;
                else if ((groupCol = addColumn('groups'))) counts.added += 1;
                else { counts.skipped += 1; continue; }
            }
            claimed.add(groupCol);
            await fillColumn(groupCol, { label: item.label || '', ...item.group }, { keepLabel: true });
            field(groupCol, 'probe_column').value = probeIndex(probeCol);
            pristine.delete(probeCol);
            pristine.delete(groupCol);
        }
        calibrationTimes(items.map(item => item.scan_time).filter(Boolean));
        // The scanned part (OD, wall, material, velocities, bevel), for the Sensitivity block
        // card's Auto-detect; a later import's values replace an earlier one's
        const scanPart = document.getElementById('id_scan_part');
        if (scanPart) {
            let part = {};
            try { part = JSON.parse(scanPart.value) || {}; } catch (e) { /* none yet */ }
            for (const item of items) Object.assign(part, item.part || {});
            scanPart.value = JSON.stringify(part);
        }
        refresh();
        root.closest('form')?.dispatchEvent(new Event('input', { bubbles: true }));
        const plural = n => `${n} column${n === 1 ? '' : 's'}`;
        const parts = [];
        if (counts.updated) parts.push(`updated ${plural(counts.updated)} from an earlier import`);
        if (counts.filled) parts.push(`filled ${plural(counts.filled)} prefilled`);
        if (counts.added) parts.push(`added ${plural(counts.added)}`);
        if (counts.skipped) parts.push(`${counts.skipped} left out: the form holds ${limits.probes} probes and ${limits.groups} groups`);
        const text = parts.join('; ') || 'nothing to add';
        const library = scopes.size ? ` Instrument from the scope library: ${[...scopes].join(', ')}.` : '';
        showStatus(text[0].toUpperCase() + text.slice(1) + '.' + library, counts.skipped > 0);
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

    // ── Keyboard: Ctrl+Shift+→ fills right (arrows between cells: arrow_nav.js) ──

    function cellInput(td) {
        return td?.querySelector('input:not([type=hidden]):not([type=checkbox]), select, textarea');
    }

    function visibleCells(tr) {
        return Array.from(tr.children).filter(cell => !cell.hidden && cell.tagName === 'TD' && cellInput(cell));
    }

    root.addEventListener('keydown', event => {
        const input = event.target;
        const td = input.closest('td');
        if (!td || !td.dataset.col) return;
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
