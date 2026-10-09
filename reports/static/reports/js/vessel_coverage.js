// Report editor, Drawings step: the vessel drawing picked for this report and its scan coverage
// rows (kept in the hidden vessel_coverage field as JSON, lengths in inches: see
// reports/services/vessel/scene.py), with the drawing redrawn as they change.

(function () {
    const box = document.getElementById('vessel-coverage');
    if (!box) return;
    const form = box.closest('form');
    const select = form.elements.vessel;
    const input = form.elements.vessel_coverage;
    const body = box.querySelector('.vessel-coverage-body');
    const rowsBox = document.getElementById('coverage-rows');
    const image = document.getElementById('coverage-image');
    const L = window.VesselLengths;
    const urlFor = (template, pk) => template.replace('/0/', `/${pk}/`).replace('/0.', `/${pk}.`);

    let marks;
    try { marks = JSON.parse(input.value || '[]'); } catch { marks = []; }
    if (!Array.isArray(marks)) marks = [];
    let parts = null;   // the picked vessel's parts, seams, nozzles and directions (parts.json)

    const STARTING = {
        part: () => ({ target: parts.parts[1]?.[0] ?? 'start' }),
        seam: () => ({ target: String(parts.seams[0] ?? '') }),
        nozzle: () => ({ target: parts.nozzles[0] ?? '' }),
        band: () => ({ start: 0, end: Math.min(parts.length, 24), from: '', to: '', style: 'grid', label: '' }),
        box: () => ({ start: 0, end: parts.length, label: 'Examination Area' }),
    };
    const KIND = { part: 'Shade', seam: 'Seam', nozzle: 'Nozzle weld', band: 'Band / grid', box: 'Box' };

    function save() {
        input.value = JSON.stringify(marks);
        schedule();
    }

    function control(tag, attrs) {
        const el = Object.assign(document.createElement(tag), attrs);
        el.classList.add(tag === 'select' ? 'form-select' : 'form-control', 'form-control-sm');
        return el;
    }

    function choose(options, value, onChange) {
        const el = control('select', {});
        for (const [v, label] of options) el.add(new Option(label, v, false, String(v) === String(value ?? '')));
        if (value && !options.some(([v]) => String(v) === String(value))) {
            el.add(new Option(`${value} (not on this vessel)`, value, false, true));
            el.classList.add('is-invalid');
        }
        el.addEventListener('change', () => { onChange(el.value); render(); save(); });
        return el;
    }

    function lengthBox(value, onValue, title) {
        const el = control('input', { type: 'text', inputMode: 'decimal', title, value: L.formatLength(value, parts.metric) });
        el.classList.add('mono');
        el.addEventListener('change', () => {
            try {
                const inches = L.parseLength(el.value, parts.metric);
                el.classList.remove('is-invalid');
                onValue(inches);
                el.value = L.formatLength(inches, parts.metric);
                save();
            } catch {
                el.classList.add('is-invalid');
            }
        });
        return el;
    }

    function render() {
        if (!parts) return;
        if (!marks.length) {
            rowsBox.replaceChildren(Object.assign(document.createElement('p'), {
                className: 'vessel-empty', textContent: 'Nothing marked yet: the drawing prints plain.',
            }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'vessel-table';
        const tbody = table.createTBody();
        const directions = [['', 'All round'], ...parts.directions.map(d => [d, d])];
        marks.forEach((mark, i) => {
            const tr = tbody.insertRow();
            tr.insertCell().textContent = KIND[mark.kind] || mark.kind;
            const cells = tr.insertCell();
            cells.className = 'vessel-coverage-cells';
            const add = (label, el) => {
                const wrap = Object.assign(document.createElement('label'), { className: 'vessel-coverage-cell' });
                if (label) wrap.append(Object.assign(document.createElement('span'), { textContent: label }));
                wrap.append(el);
                cells.append(wrap);
            };
            if (mark.kind === 'part') add('', choose(parts.parts, mark.target, v => { mark.target = v; }));
            if (mark.kind === 'seam') add('', choose(parts.seams.map(n => [n, `Seam ${n}`]), mark.target, v => { mark.target = v; }));
            if (mark.kind === 'nozzle') add('', choose(parts.nozzles.map(t => [t, t]), mark.target, v => { mark.target = v; }));
            if (mark.kind === 'band' || mark.kind === 'box') {
                add('From', lengthBox(mark.start, v => { mark.start = v; }, `Along the shell from the ${parts.start} tangent line`));
                add('to', lengthBox(mark.end, v => { mark.end = v; }, ''));
            }
            if (mark.kind === 'band') {
                add('round from', choose(directions, mark.from, v => { mark.from = v; }));
                add('to', choose(directions, mark.to, v => { mark.to = v; }));
                add('', choose([['grid', 'Grid'], ['solid', 'Shaded']], mark.style, v => { mark.style = v; }));
            }
            if (mark.kind === 'band' || mark.kind === 'box') {
                const label = control('input', { type: 'text', value: mark.label || '', maxLength: 80, placeholder: 'Label' });
                label.addEventListener('input', () => { mark.label = label.value; save(); });
                add('', label);
            }
            const remove = Object.assign(document.createElement('button'), {
                type: 'button', className: 'btn btn-sm btn-secondary', title: 'Remove', innerHTML: '<i class="bi bi-x-lg"></i>',
            });
            remove.addEventListener('click', () => { marks.splice(i, 1); render(); save(); });
            tr.insertCell().append(remove);
        });
        rowsBox.replaceChildren(table);
    }

    let timer = null;
    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(redraw, 300);
    }

    function redraw() {
        if (!select.value) return;
        const url = urlFor(box.dataset.pngUrl, select.value);
        image.src = `${url}?coverage=${encodeURIComponent(JSON.stringify(marks))}`;
    }

    async function load() {
        body.hidden = !select.value;
        parts = null;
        if (!select.value) return;
        try {
            parts = await (await fetch(urlFor(box.dataset.partsUrl, select.value))).json();
        } catch {
            rowsBox.textContent = "The vessel's parts couldn't be loaded.";
            return;
        }
        box.querySelector('[data-coverage-start]').textContent = parts.start;
        render();
        redraw();
    }

    document.getElementById('coverage-add').addEventListener('change', event => {
        const kind = event.target.value;
        event.target.value = '';
        if (!kind || !parts) return;
        marks.push({ kind, ...STARTING[kind]() });
        render();
        save();
    });

    select.addEventListener('change', load);
    load();
})();
