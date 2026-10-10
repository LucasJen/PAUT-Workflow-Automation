// The Setup values table in each setup block: everything the setup's .nde gave (part, instrument and
// probe, UT settings, focal law, gates, TCG), in the setup's units, to check and change before it's
// printed. The file's values stay in the setup's hidden nde_sheet; changes are kept beside them
// ({"edits": {"part.thickness": 0.0254, ...}}, SI like the file) and the setup picture is drawn with
// them (setup_sheet.apply_edits). A value with a report field of its own (thickness, instrument,
// probe, velocity...) fills that field too, and typing in that field changes the value here.

(function () {
    const schemaNode = document.getElementById('setup-values-schema');
    if (!schemaNode) return;
    const SCHEMA = JSON.parse(schemaNode.textContent);
    const previewUrl = document.getElementById('setup-formset-container')?.dataset.sheetPreviewUrl;
    const M_PER_IN = 0.0254;
    const el = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };
    const plain = (v, places) => {
        const text = Number(v).toFixed(places);
        return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
    };

    function readSheet(block) {
        const input = block.querySelector('input[name$="-nde_sheet"]');
        if (!input || !input.value.trim()) return null;
        try {
            const data = JSON.parse(input.value);
            return data && typeof data === 'object' ? data : null;
        } catch {
            return null;
        }
    }
    function writeSheet(block, data) {
        const input = block.querySelector('input[name$="-nde_sheet"]');
        input.value = JSON.stringify(data);
        input.dispatchEvent(new Event('input', { bubbles: true }));   // the page's unsaved-changes mark
    }
    const unitsOf = block => block.querySelector('select[name$="-units"]')?.value === 'metric' ? 'metric' : 'imperial';
    const fieldInput = (block, name) => block.querySelector(`[name$="-${name}"]`);

    function get(data, path) {
        let node = data;
        for (const part of path.split('.')) {
            if (node === null || node === undefined) return undefined;
            node = node[/^\d+$/.test(part) && Array.isArray(node) ? +part : part];
        }
        return node;
    }
    /** The value shown: the user's change, else the file's. */
    const value = (data, path) => (data.edits && path in data.edits ? data.edits[path] : get(data, path));

    // ── How each kind of value is shown, typed and written to its report field ──
    function kinds(data, units) {
        const metric = units === 'metric';
        const velocity = () => Number(value(data, 'ut.velocity')) || 0;
        const firstAngle = () => (Array.isArray(data.beams) && data.beams[0] ? Number(data.beams[0][1]) || 0 : 0);
        const length = { unit: metric ? 'mm' : 'in', show: m => (metric ? (m * 1000).toFixed(2) : (m / M_PER_IN).toFixed(3)),
                         read: v => (metric ? v / 1000 : v * M_PER_IN) };
        const path = cos => ({ unit: length.unit, show: s => length.show(s * velocity() / 2 * cos()),
                               read: v => (velocity() ? 2 * length.read(v) / velocity() / cos() : null) });
        return {
            length,
            velocity: { unit: metric ? 'm/s' : 'in/µs', show: v => (metric ? Number(v).toFixed(0) : (v / 25400).toFixed(4)),
                        read: v => (metric ? v : v * 25400) },
            mhz: { unit: 'MHz', show: v => plain(v / 1e6, 2), read: v => v * 1e6 },
            hz: { unit: 'Hz', show: v => plain(v, 1), read: v => v },
            us: { unit: 'µs', show: v => plain(v * 1e6, 2), read: v => v / 1e6 },
            ns: { unit: 'ns', show: v => plain(v * 1e9, 1), read: v => v / 1e9 },
            db: { unit: 'dB', show: v => plain(v, 1), read: v => v },
            deg: { unit: '°', show: v => plain(v, 2), read: v => v },
            volts: { unit: 'V', show: v => plain(v, 1), read: v => v },
            percent: { unit: '%', show: v => plain(v, 1), read: v => v },
            int: { unit: '', show: v => plain(v, 0), read: v => Math.round(v) },
            number: { unit: '', show: v => plain(v, 2), read: v => v },
            path: path(() => 1),                                                   // a time as half-path distance
            depth: path(() => Math.cos(firstAngle() * Math.PI / 180) || 1),       // ... as true depth (TCG)
            text: null,
        };
    }

    /** The rows: the fixed ones from the schema, then each gate's and TCG point's. */
    function sections(data) {
        const out = SCHEMA.map(s => ({ title: s.title, rows: s.rows }));
        const gates = Array.isArray(data.gates) ? data.gates : [];
        if (gates.length) {
            out.push({ title: 'Gates', rows: gates.flatMap((g, i) => {
                const name = g.name ? `Gate ${g.name}` : `Gate ${i + 1}`;
                return [{ path: `gates.${i}.start`, label: `${name} start`, kind: 'path' },
                        { path: `gates.${i}.length`, label: `${name} width`, kind: 'path' },
                        { path: `gates.${i}.threshold`, label: `${name} threshold`, kind: 'percent' }];
            }) });
        }
        const tcg = Array.isArray(data.tcg) ? data.tcg : [];
        if (tcg.length) {
            out.push({ title: 'TCG', rows: tcg.flatMap((_, i) => [
                { path: `tcg.${i}.0`, label: `Point ${i + 1} depth`, kind: 'depth' },
                { path: `tcg.${i}.1`, label: `Point ${i + 1} gain`, kind: 'db' }]) });
        }
        return out;
    }

    function render(block) {
        const box = block.querySelector('[data-setup-values]');
        if (!box) return;
        const data = readSheet(block);
        box.hidden = !data;
        if (!data) { box.replaceChildren(); return; }
        const units = unitsOf(block);
        const kind = kinds(data, units);
        const wasOpen = box.querySelector('details')?.open ?? true;
        const edited = Object.keys(data.edits || {}).length;

        const grid = el('div', { className: 'setup-values-grid' });
        for (const section of sections(data)) {
            // Part always (thickness may be missing from the file); other sections only with values
            const rows = section.rows.filter(r => section.title === 'Part' || value(data, r.path) !== undefined);
            if (!rows.length) continue;
            grid.append(el('div', { className: 'setup-values-head', textContent: section.title }));
            for (const row of rows) {
                const k = kind[row.kind];
                const current = value(data, row.path), original = get(data, row.path);
                const changed = data.edits && row.path in data.edits;
                const shown = current === undefined || current === null || current === '' ? ''
                    : k ? k.show(Number(current)) : String(current);
                const input = el('input', { type: 'text', className: 'form-control form-control-sm', value: shown });
                if (k) { input.inputMode = 'decimal'; input.classList.add('mono'); }
                input.dataset.path = row.path;
                input.addEventListener('change', () => change(block, row, input.value));
                const fromFile = original === undefined || original === null || original === '' ? 'nothing'
                    : k ? `${k.show(Number(original))} ${k.unit}`.trim() : String(original);
                const label = el('label', { className: 'setup-values-label', textContent: row.label,
                                            title: row.field ? `Also fills the report's ${row.field.replace(/_/g, ' ')} field` : '' });
                const cell = el('div', { className: `setup-values-cell${changed ? ' is-changed' : ''}` }, input,
                                el('span', { className: 'setup-values-unit', textContent: k?.unit || '' }));
                if (changed) {
                    const back = el('button', { type: 'button', className: 'btn btn-sm btn-link setup-values-reset', title: `Back to the file's value (${fromFile})`,
                                                innerHTML: '<i class="bi bi-arrow-counterclockwise"></i>' });
                    back.addEventListener('click', () => change(block, row, null));
                    cell.append(back);
                    cell.title = `Changed - the file says ${fromFile}`;
                }
                grid.append(label, cell);
            }
        }

        const preview = el('button', { type: 'button', className: 'btn btn-secondary btn-sm', innerHTML: '<i class="bi bi-image"></i> Preview the setup picture' });
        preview.addEventListener('click', () => showPreview(block));
        const resetAll = el('button', { type: 'button', className: 'btn btn-ghost btn-sm', innerHTML: '<i class="bi bi-arrow-counterclockwise"></i> All back to the file', hidden: !edited });
        resetAll.addEventListener('click', () => {
            const sheet = readSheet(block);
            const paths = Object.keys(sheet.edits || {});
            delete sheet.edits;
            writeSheet(block, sheet);
            for (const p of paths) fillField(block, sheet, findRow(sheet, p));
            render(block);
        });
        const summary = el('summary', {}, el('span', { className: 'setup-values-title', textContent: 'Setup values from the .nde' }),
                           el('span', { className: 'setup-values-note', textContent: edited ? `${edited} changed` : 'as the file gave them' }));
        const details = el('details', { open: wasOpen }, summary,
                           el('p', { className: 'form-text', textContent: 'Change any value before it goes on the setup picture and into the report. Values with a report field of their own fill it too.' }),
                           grid,
                           el('div', { className: 'setup-values-actions' }, preview, resetAll),
                           el('div', { className: 'setup-values-preview', hidden: true }));
        box.replaceChildren(details);
    }

    function findRow(data, path) {
        for (const s of sections(data)) for (const r of s.rows) if (r.path === path) return r;
        return null;
    }

    /** A typed change (null: back to the file's value): kept in the sheet, and in the report field it fills. */
    function change(block, row, text) {
        const data = readSheet(block);
        if (!data) return;
        const k = kinds(data, unitsOf(block))[row.kind];
        data.edits = data.edits || {};
        if (text === null) {
            delete data.edits[row.path];
        } else {
            let v = String(text).trim();
            if (k && v !== '') {
                const n = parseFloat(v);
                if (!Number.isFinite(n)) { render(block); return; }
                v = k.read(n);
            }
            const original = get(data, row.path);
            if (v === original || (k && v !== '' && original !== undefined && Math.abs(v - original) <= Math.abs(original) * 1e-9)) delete data.edits[row.path];
            else data.edits[row.path] = v;
        }
        if (!Object.keys(data.edits).length) delete data.edits;
        writeSheet(block, data);
        fillField(block, data, row);
        render(block);
        if (row.path === 'ut.velocity') render(block);   // gates and TCG are shown at the velocity
    }

    /** The report field a value fills, in the import's format (as shown here, without the unit). */
    function fillField(block, data, row) {
        if (!row?.field) return;
        const input = fieldInput(block, row.field);
        if (!input) return;
        const k = kinds(data, unitsOf(block))[row.kind];
        const v = value(data, row.path);
        input.value = v === undefined || v === null || v === '' ? '' : k ? k.show(Number(v)) : String(v);
        input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    /** Typing in a report field that a value fills changes the value too. */
    document.addEventListener('change', e => {
        const block = e.target.closest?.('.setup-block');
        if (!block || e.target.closest('[data-setup-values]')) return;
        if (e.target.matches('select[name$="-units"]')) { setTimeout(() => render(block), 0); return; }
        const data = readSheet(block);
        if (!data) return;
        const name = (e.target.name || '').replace(/^.*-/, '');
        for (const s of SCHEMA) {
            for (const row of s.rows) {
                if (row.field !== name) continue;
                const k = kinds(data, unitsOf(block))[row.kind];
                let v = e.target.value.trim();
                if (k && v !== '') { const n = parseFloat(v); if (!Number.isFinite(n)) return; v = k.read(n); }
                data.edits = data.edits || {};
                const original = get(data, row.path);
                if (v === original || (k && original !== undefined && v !== '' && Math.abs(v - original) <= Math.abs(original) * 1e-6)) delete data.edits[row.path];
                else data.edits[row.path] = v;
                if (!Object.keys(data.edits).length) delete data.edits;
                writeSheet(block, data);
                render(block);
                return;
            }
        }
    });

    async function showPreview(block) {
        const box = block.querySelector('.setup-values-preview');
        if (!box || !previewUrl) return;
        box.hidden = false;
        box.closest('details').open = true;
        box.replaceChildren(el('p', { className: 'form-text', textContent: 'Drawing the setup picture…' }));
        box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        const form = block.closest('form');
        const body = new FormData();
        body.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
        body.append('nde_sheet', block.querySelector('input[name$="-nde_sheet"]').value);
        body.append('units', unitsOf(block));
        for (const name of ['specimen_thickness', 'tr_max', 'weld_bevel_angle', 'weld_root_face', 'weld_root_gap', 'weld_cap_width',
                            'index_offset', 'extra_offsets']) body.append(name, fieldInput(block, name)?.value || '');
        if (fieldInput(block, 'weld_on')?.checked) body.append('weld_on', 'on');
        body.append('report_type', document.getElementById('id_report_type')?.value || '');
        try {
            const response = await fetch(previewUrl, { method: 'POST', body });
            if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || "The picture couldn't be drawn.");
            const url = URL.createObjectURL(await response.blob());
            const close = el('button', { type: 'button', className: 'btn btn-sm btn-ghost', innerHTML: '<i class="bi bi-x-lg"></i> Close' });
            close.addEventListener('click', () => { box.hidden = true; box.replaceChildren(); URL.revokeObjectURL(url); });
            box.replaceChildren(el('div', { className: 'setup-values-actions' }, el('span', { className: 'form-text', textContent: 'As it will be printed (the report saves your changes when you save it).' }), close),
                                el('img', { src: url, alt: 'Setup picture preview' }));
        } catch (err) {
            box.replaceChildren(el('p', { className: 'form-text text-danger', textContent: err.message }));
        }
    }

    // Setups on the page, ones added later, and ones filled from a file or a saved setup
    document.querySelectorAll('.setup-block').forEach(render);
    document.addEventListener('setup-filled', e => render(e.target.closest('.setup-block') || e.target));
    new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(node => {
        if (node.nodeType === 1 && node.matches?.('.setup-block')) render(node);
    }))).observe(document.getElementById('setup-formset-container') || document.body, { childList: true });
    window.SetupValues = { render, preview: showPreview };
})();
