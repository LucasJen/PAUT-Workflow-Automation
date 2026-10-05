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
    const PAUT = 'paut';     // weld_form.PAUT: a column's kind when none is given

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

    // Wedge dia. follows the pipe: the item inspected's diameter on the Sensitivity block & test
    // material card (read-only here; the save sets it the same way)
    const pipeDiameter = root.closest('form')?.elements.item_diameter;
    function mirrorPipeDiameter(col, na) {
        const input = field(col, 'wedge_diameter');
        if (!input || !pipeDiameter || na.has('wedge_diameter')) return;
        input.readOnly = true;
        input.title = 'The pipe diameter (Item inspected on the Sensitivity block & test material card)';
        if (input.value !== pipeDiameter.value) input.value = pipeDiameter.value;
    }
    if (pipeDiameter) {
        // Changes to the card (typed, a block picked, Auto-detect) show here at once
        ['input', 'change'].forEach(type => root.closest('form').addEventListener(type, () => applyKinds()));
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
            mirrorPipeDiameter(col, na);
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

    async function fillColumn(col, values) {
        for (const [name, value] of Object.entries(values)) {
            if (name === 'catalogue_probe' || name === 'catalogue_wedge' || name === 'probe_column') continue;
            const input = field(col, name);
            if (!input || value === null || value === undefined) continue;
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

    function pickColumn(kind, index, defaultKind, ofColumn, used) {
        const cols = columns(kind).filter(col => !used.has(col));
        const inPlace = columns(kind)[index];
        if (inPlace && !used.has(inPlace) && ofColumn(inPlace) === defaultKind) return inPlace;
        return cols.find(col => ofColumn(col) === defaultKind) || null;
    }

    async function overlayDefaultColumns(type) {
        const { probes = [], groups = [] } = typeDefaults(type);
        const used = new Set();
        const probeAt = {};   // default probe index -> the report's column
        let updated = 0;
        for (const [i, values] of probes.entries()) {
            const kind = values.kind || PAUT;
            const col = pickColumn('probes', i, kind, c => field(c, 'kind').value, used);
            if (!col) continue;
            used.add(col);
            probeAt[String(i)] = col;
            const { kind: _, catalogue_probe: probe, catalogue_wedge: wedge, ...rest } = values;
            await fillColumn(col, Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== null && v !== '')));
            if (probe && window.CatalogueSelect) await window.CatalogueSelect.setPair(field(col, 'catalogue_probe'), probe, wedge || null);
            updated += 1;
        }
        for (const [i, values] of groups.entries()) {
            const column = String(values.probe_column ?? '');
            const kind = column === NOT_USED ? NOT_USED : (probes[Number(column)]?.kind || (column === '' ? null : PAUT));
            const col = pickColumn('groups', i, kind, c => probeKind(field(c, 'probe_column').value), used);
            if (!col) continue;
            used.add(col);
            const { probe_column: _, ...rest } = values;
            await fillColumn(col, Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== null && v !== '')));
            updated += 1;
        }
        refresh();
        return updated;
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
        // "Reload defaults" (create_report.js): an empty grid gets the default columns; otherwise each
        // default column's values go over the report's column of the same kind (the one in its
        // place, else the next of that kind). Returns what it did, for the status line.
        window.WeldGrid = {
            async reloadDefaultColumns() {
                if (empty()) {
                    await addDefaultColumns(typeSelect.value);
                    return 'added';
                }
                return (await overlayDefaultColumns(typeSelect.value)) ? 'updated' : '';
            },
        };
        typeSelect.addEventListener('change', async () => {
            for (const col of pristine) removeColumn(col.split('-')[0], col);
            pristine.clear();
            if (empty()) await addDefaultColumns(typeSelect.value);
        });
    }

    // ── Import: .nde groups and saved setups replace the columns ──────────────────
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

    const probeIndex = col => col.split('-')[1];

    // A new column's blanks from the report type's default column of the same kind (the one in
    // its place, else the next unused one): cable, probe check, labels... that a file doesn't have
    function fillBlanksFromDefaults(kind, cols, kindOf) {
        const defaults = (typeSelect ? typeDefaults(typeSelect.value)[kind] : null) || [];
        const used = new Set();
        const defaultKind = values => kind === 'probes' ? (values.kind || PAUT)
            : values.probe_column === NOT_USED ? NOT_USED
            : (typeDefaults(typeSelect.value).probes?.[Number(values.probe_column)]?.kind || PAUT);
        cols.forEach((col, i) => {
            const want = kindOf(col);
            let at = defaults[i] && !used.has(i) && defaultKind(defaults[i]) === want ? i : -1;
            if (at < 0) at = defaults.findIndex((values, j) => !used.has(j) && defaultKind(values) === want);
            if (at < 0) return;
            used.add(at);
            for (const [name, value] of Object.entries(defaults[at])) {
                if (['kind', 'probe_column', 'catalogue_probe', 'catalogue_wedge', 'source_file'].includes(name)) continue;
                const input = field(col, name);
                if (input && !input.value.trim() && value !== null && value !== '') input.value = value;
            }
        });
    }

    // Each import replaces the grid: every probe and group column there is removed, and the
    // file's (or saved setup's) probes and groups go in new columns. Within one import:
    // - a probe used by several groups (same probe in the file, or the same model and S/N) gets
    //   one column;
    // - a group with the same settings on the same probe (the same setup scanned on another weld
    //   or side) is one column.
    // Blanks the file leaves (cable, probe check, labels...) come from the report type's defaults.
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
        let replaced = 0;
        for (const kind of ['probes', 'groups']) {
            for (const col of columns(kind)) {
                removeColumn(kind, col);
                if (kind === 'probes') replaced += 1;
            }
        }
        pristine.clear();
        let skipped = 0;
        const scopes = new Set();   // instruments found in the scope library
        const placed = {};          // probe_ref -> probe column
        const newProbes = [];
        const newGroups = [];
        for (const item of items) {
            // The instrument: the file's, with what the scope library knows by S/N (cal due,
            // module, scanner type, analysis software); what neither has stays as typed
            for (const [name, value] of Object.entries(item.instrument || {})) {
                const input = document.getElementById(`id_${name}`);
                if (input) input.value = value;
            }
            if (item.scope) scopes.add(item.scope);

            let probeCol = (item.probe_ref && placed[item.probe_ref])
                || (item.probe_key ? newProbes.find(col => pageProbeKey(col) === item.probe_key) : null);
            if (!probeCol) {
                probeCol = addColumn('probes');
                if (!probeCol) { skipped += 1; continue; }
                await fillColumn(probeCol, item.probe);
                newProbes.push(probeCol);
            }
            if (item.probe_ref) placed[item.probe_ref] = probeCol;

            const settings = Object.entries(item.group).filter(([k, v]) => k !== 'source_file' && v !== '' && v != null);
            const same = settings.length && newGroups.find(col =>
                field(col, 'probe_column').value === probeIndex(probeCol)
                && settings.every(([k, v]) => !field(col, k) || field(col, k).value === String(v)));
            if (same) continue;
            const groupCol = addColumn('groups');
            if (!groupCol) { skipped += 1; continue; }
            await fillColumn(groupCol, { label: item.label || '', ...item.group });
            field(groupCol, 'probe_column').value = probeIndex(probeCol);
            newGroups.push(groupCol);
        }
        fillBlanksFromDefaults('probes', newProbes, col => field(col, 'kind').value || PAUT);
        fillBlanksFromDefaults('groups', newGroups, col => probeKind(field(col, 'probe_column').value) || PAUT);
        calibrationTimes(items.map(item => item.scan_time).filter(Boolean));
        // The scanned part (OD, wall, material, velocities, bevel), for the Sensitivity block
        // card's Auto-detect; a later import's values replace an earlier one's
        const scanPart = document.getElementById('id_scan_part');
        if (scanPart) {
            let part = {};
            try { part = JSON.parse(scanPart.value) || {}; } catch (e) { /* none yet */ }
            for (const item of items) Object.assign(part, item.part || {});
            scanPart.value = JSON.stringify(part);
            if (items.some(item => item.part && Object.keys(item.part).length)) window.Materials?.autoDetectIfEmpty();
        }
        refresh();
        root.closest('form')?.dispatchEvent(new Event('input', { bubbles: true }));
        const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
        const parts = [`${plural(newProbes.length, 'probe')} and ${plural(newGroups.length, 'group')} imported`];
        if (replaced) parts.push(`replaced the ${plural(replaced, 'probe')} there`);
        if (skipped) parts.push(`${skipped} left out: the form holds ${limits.probes} probes and ${limits.groups} groups`);
        const text = parts.join('; ');
        showStatus(text + '.' + library, skipped > 0);
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
