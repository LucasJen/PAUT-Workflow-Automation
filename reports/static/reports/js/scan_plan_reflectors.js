// Scan plan reflectors (advanced): a row per reflector - name, type, weld side, distance from the
// weld C/L, depth, size and tilt - kept in the hidden `reflectors` field as JSON with lengths in
// inches (reports/services/scan_plan/reflectors.py). Lengths show in the plan's units; a value a
// type doesn't use is left out (its box is greyed). Editing redraws the drawing.

(function () {
    const input = document.querySelector('[name="reflectors"]');
    const editor = document.getElementById('reflector-editor');
    if (!input || !editor) return;
    const form = input.form;
    const kinds = JSON.parse(document.getElementById('reflector-kinds').textContent);
    const SHORT = { sdh: 'SDH', od_notch: 'OD notch', id_notch: 'ID notch', flaw: 'Flaw', sidewall: 'LOF' };
    const uses = JSON.parse(document.getElementById('reflector-uses').textContent);
    const rowsBox = editor.querySelector('.reflector-rows');
    const LENGTHS = ['distance', 'depth', 'size'];
    const COLUMNS = [
        ['label', 'Name', 'Shown beside it in the drawing'],
        ['kind', 'Type', ''],
        ['side', 'Side', "The weld side it's on: the 90° skew's (where its probe sits) or the 270° skew's"],
        ['distance', 'From C/L', 'Weld centre line to it (along the OD on a pipe)'],
        ['depth', 'Depth', "Below the OD: a hole's centre, a flaw's middle, or where a sidewall flaw is centred on the fusion face"],
        ['size', 'Size', "A hole's diameter, or a notch's / flaw's height"],
        ['angle', 'Tilt (°)', 'From vertical; positive leans its top towards the weld centre line'],
    ];
    // New reflectors start at sizes that suit a typical weld (inches)
    const STARTING = {
        sdh: { distance: 0, depth: 0.5, size: 0.0625 },
        od_notch: { distance: 0.25, size: 0.04, angle: 0 },
        id_notch: { distance: 0.05, size: 0.04, angle: 0 },
        flaw: { distance: 0, depth: 0.5, size: 0.1, angle: 0 },
        sidewall: { depth: 0.5, size: 0.1 },
    };

    let rows;
    try { rows = JSON.parse(input.value || '[]'); } catch { rows = []; }
    if (!Array.isArray(rows)) rows = [];

    const metric = () => form.elements.units?.value === 'metric';
    const shown = (name, value) => {
        if (value === undefined || value === null || value === '') return '';
        if (!LENGTHS.includes(name)) return +Number(value).toFixed(2);
        return metric() ? +(value * 25.4).toFixed(2) : +Number(value).toFixed(4);
    };
    const stored = (name, text) => {
        const value = parseFloat(text);
        if (Number.isNaN(value)) return '';
        return LENGTHS.includes(name) && metric() ? value / 25.4 : value;
    };

    function save() {
        input.value = JSON.stringify(rows);
        form.dispatchEvent(new Event('input'));
    }

    function render() {
        if (!rows.length) {
            rowsBox.replaceChildren(Object.assign(document.createElement('p'), {
                className: 'reflector-empty', textContent: 'No reflectors. Add one to see which beams reach it.',
            }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'reflector-table';
        const head = table.createTHead().insertRow();
        for (const [, label, help] of COLUMNS) {
            const th = document.createElement('th');
            th.textContent = label;
            if (help) th.title = help;
            head.append(th);
        }
        head.append(document.createElement('th'));
        const body = table.createTBody();
        rows.forEach((row, i) => {
            const tr = body.insertRow();
            for (const [name] of COLUMNS) {
                const cell = tr.insertCell();
                let control;
                if (name === 'kind') {
                    control = document.createElement('select');
                    for (const [value, label] of Object.entries(kinds)) control.add(new Option(label, value, false, value === row.kind));
                } else if (name === 'side') {
                    control = document.createElement('select');
                    control.add(new Option('90°', '90', false, String(row.side) !== '270'));
                    control.add(new Option('270°', '270', false, String(row.side) === '270'));
                } else {
                    control = document.createElement('input');
                    control.type = 'text';
                    control.inputMode = name === 'label' ? 'text' : 'decimal';
                    const used = name === 'label' || uses[row.kind].includes(name);
                    control.disabled = !used;
                    control.value = name === 'label' ? (row.label || '') : (used ? shown(name, row[name]) : '');
                    if (name === 'label') control.placeholder = `${SHORT[row.kind]} ${i + 1}`;   // the name it gets
                    if (name !== 'label') control.classList.add('mono');
                }
                control.classList.add(control.tagName === 'SELECT' ? 'form-select' : 'form-control', 'form-control-sm');
                control.dataset.name = name;
                control.dataset.row = i;
                cell.append(control);
            }
            const remove = Object.assign(document.createElement('button'), {
                type: 'button', className: 'btn btn-sm btn-secondary', title: 'Remove this reflector',
                innerHTML: '<i class="bi bi-x-lg"></i>',
            });
            remove.addEventListener('click', () => { rows.splice(i, 1); render(); save(); });
            tr.insertCell().append(remove);
        });
        rowsBox.replaceChildren(table);
    }

    rowsBox.addEventListener('input', event => {
        const { name, row } = event.target.dataset;
        if (!name || name === 'kind' || name === 'side') return;
        rows[row][name] = name === 'label' ? event.target.value : stored(name, event.target.value);
        event.stopPropagation();   // the form's own redraw listener runs from save()
        save();
    });
    rowsBox.addEventListener('change', event => {
        const { name, row } = event.target.dataset;
        if (name !== 'kind' && name !== 'side') return;
        rows[row][name] = name === 'side' ? Number(event.target.value) : event.target.value;
        if (name === 'kind') rows[row] = { ...STARTING[rows[row].kind], ...rows[row] };
        event.stopPropagation();
        render();
        save();
    });

    document.getElementById('reflector-add').addEventListener('change', event => {
        const kind = event.target.value;
        if (!kind) return;
        event.target.value = '';
        const thickness = parseFloat(form.elements.thickness.value);
        const start = { ...STARTING[kind] };
        if ('depth' in start && thickness > 0) start.depth = (metric() ? thickness / 25.4 : thickness) / 2;
        rows.push({ kind, side: 90, ...start });
        render();
        save();
    });

    // The units switch changes how the lengths show, not what's stored
    form.elements.units?.addEventListener('change', render);
    render();
})();
