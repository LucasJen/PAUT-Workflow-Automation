// Vessel drawing editor: the course and nozzle rows (kept in the hidden courses / nozzles fields as
// JSON, lengths in inches), lengths typed as on the client drawing (14'-0", 66", or mm when metric:
// the same reading as reports/services/vessel/lengths.py), the type's own head names and starting
// shape, and the live drawing redrawn from the form's values as they change.

(function () {
    const form = document.getElementById('vessel-form');
    if (!form) return;
    const fields = document.getElementById('vessel-fields');
    const courseInput = form.elements.courses;
    const nozzleInput = form.elements.nozzles;
    const typeStarts = JSON.parse(document.getElementById('vessel-type-starts').textContent);
    const directions = JSON.parse(document.getElementById('vessel-directions').textContent);
    const image = document.getElementById('vessel-image');
    const status = document.getElementById('vessel-status');
    const MM_PER_IN = 25.4;
    const HORIZONTAL = ['horizontal', 'exchanger'];
    // The heads' names by type: [start, end, start (short)]
    const ENDS = {
        horizontal: ['Left head', 'Right head', 'left'],
        exchanger: ['Channel end (left)', 'Far end (right)', 'left'],
        vertical: ['Bottom head', 'Top head', 'bottom'],
        tank: ['Bottom', 'Roof', 'bottom'],
    };

    const parse = (text, holder) => {
        try { return JSON.parse(text || '[]'); } catch { return holder; }
    };
    let courses = parse(courseInput.value, []);
    let nozzles = parse(nozzleInput.value, []);
    const metric = () => form.elements.units?.value === 'metric';
    const vesselType = () => form.elements.vessel_type.value;
    const horizontal = () => HORIZONTAL.includes(vesselType());

    // ── lengths ──────────────────────────────────────────────────────
    function inchesPart(text) {
        let total = 0;
        for (const token of text.trim().split(/[\s-]+/)) {
            if (!token) continue;
            const fraction = token.match(/^(\d+)\/(\d+)$/);
            if (fraction) {
                if (+fraction[2] === 0) throw new Error(token);
                total += +fraction[1] / +fraction[2];
            } else if (/^\d*\.?\d+$/.test(token)) {
                total += parseFloat(token);
            } else {
                throw new Error(token);
            }
        }
        return total;
    }

    /** Inches for a typed length, null when blank; throws when it can't be read. */
    function parseLength(text, isMetric = metric()) {
        let t = String(text ?? '').trim().toLowerCase().replace(/′/g, "'").replace(/″|''/g, '"');
        if (!t) return null;
        if (t.endsWith('mm')) {
            const mm = parseFloat(t.slice(0, -2));
            if (Number.isNaN(mm)) throw new Error(text);
            return mm / MM_PER_IN;
        }
        if (isMetric && !t.includes("'") && !t.includes('"')) {
            if (!/^\d*\.?\d+$/.test(t)) throw new Error(text);
            return parseFloat(t) / MM_PER_IN;
        }
        t = t.replace(/ft/g, "'").replace(/in/g, '"');
        const at = t.lastIndexOf("'");
        const feet = at >= 0 ? t.slice(0, at).trim() : '';
        if (feet && !/^\d*\.?\d+$/.test(feet)) throw new Error(text);
        const rest = (at >= 0 ? t.slice(at + 1) : t).replace(/"/g, ' ').replace(/^[\s-]+/, '');
        return (feet ? parseFloat(feet) * 12 : 0) + inchesPart(rest);
    }

    function inchesText(inches) {
        let whole = Math.floor(inches);
        let sixteenths = Math.round((inches - whole) * 16);
        if (sixteenths >= 16) { whole += 1; sixteenths -= 16; }
        if (!sixteenths) return String(whole);
        let n = sixteenths, d = 16;
        while (n % 2 === 0) { n /= 2; d /= 2; }
        return whole ? `${whole} ${n}/${d}` : `${n}/${d}`;
    }

    /** A stored length as it shows: '1676 mm', or ft-in from `feetFrom` inches up and inches below. */
    function formatLength(inches, isMetric = metric(), feetFrom = 36) {
        if (inches === null || inches === undefined || inches === '') return '';
        if (isMetric) return `${+(inches * MM_PER_IN).toFixed(1)} mm`;
        const value = Math.round(inches * 16) / 16;
        if (Math.abs(value) >= feetFrom) {
            const sign = value < 0 ? '-' : '';
            const abs = Math.abs(value);
            const feet = Math.floor(abs / 12);
            return `${sign}${feet}'-${inchesText(abs - feet * 12)}"`;
        }
        return value < 0 ? `-${inchesText(-value)}"` : `${inchesText(value)}"`;
    }
    const formatDiameter = (inches, isMetric = metric()) => formatLength(inches, isMetric, 120);

    // ── the rows ─────────────────────────────────────────────────────
    function save() {
        courseInput.value = JSON.stringify(courses);
        nozzleInput.value = JSON.stringify(nozzles);
        schedule();
    }

    function control(tag, attrs) {
        const el = document.createElement(tag);
        Object.assign(el, attrs);
        el.classList.add(tag === 'select' ? 'form-select' : 'form-control', 'form-control-sm');
        return el;
    }

    function button(icon, title, onClick, disabled = false) {
        const b = Object.assign(document.createElement('button'), {
            type: 'button', className: 'btn btn-sm btn-secondary', title, disabled, innerHTML: `<i class="bi bi-${icon}"></i>`,
        });
        b.addEventListener('click', onClick);
        return b;
    }

    function lengthBox(value, onValue, options = {}) {
        const input = control('input', {
            type: 'text', inputMode: 'decimal', value: options.diameter ? formatDiameter(value) : formatLength(value),
            placeholder: options.placeholder || '',
        });
        input.classList.add('mono');
        input.addEventListener('change', () => {
            try {
                const inches = parseLength(input.value);
                input.classList.remove('is-invalid');
                onValue(inches);
                input.value = options.diameter ? formatDiameter(inches) : formatLength(inches);
                save();
            } catch {
                input.classList.add('is-invalid');
                input.title = metric() ? 'Type it in mm, e.g. 1676' : 'Type it like 14\'-0", 66" or 66';
            }
        });
        return input;
    }

    const KIND_LABEL = { course: 'Course', cone: 'Cone', flange: 'Flange' };

    function renderCourses() {
        const box = document.getElementById('course-rows');
        if (!courses.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), {
                className: 'vessel-empty', textContent: 'No courses yet. Add one, or split a length into equal courses.',
            }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'vessel-table';
        const head = table.createTHead().insertRow();
        for (const [label, help] of [['', ''], ['Type', ''], ['Length', 'Along the vessel'],
            ['Diameter', "Blank = the vessel's"], ['Label', 'Written inside the course on the drawing, e.g. Channel'], ['', '']]) {
            const th = document.createElement('th');
            th.textContent = label;
            if (help) th.title = help;
            head.append(th);
        }
        const body = table.createTBody();
        let courseNumber = 0;
        courses.forEach((row, i) => {
            const tr = body.insertRow();
            tr.insertCell().textContent = row.kind === 'course' ? `${++courseNumber}` : '';
            tr.cells[0].className = 'vessel-row-number';
            tr.insertCell().textContent = KIND_LABEL[row.kind] || row.kind;
            const length = tr.insertCell();
            if (row.kind !== 'flange') length.append(lengthBox(row.length, v => { row.length = v; }));
            const diameter = tr.insertCell();
            if (row.kind === 'course') {
                diameter.append(lengthBox(row.diameter, v => { row.diameter = v; },
                    { diameter: true, placeholder: form.elements.diameter.value }));
            }
            const label = tr.insertCell();
            if (row.kind === 'course') {
                const input = control('input', { type: 'text', value: row.label || '', maxLength: 40 });
                input.addEventListener('input', () => { row.label = input.value; save(); });
                label.append(input);
            }
            const actions = tr.insertCell();
            actions.className = 'vessel-row-buttons';
            actions.append(
                button('arrow-up', 'Move up', () => { [courses[i - 1], courses[i]] = [courses[i], courses[i - 1]]; renderCourses(); save(); }, i === 0),
                button('arrow-down', 'Move down', () => { [courses[i + 1], courses[i]] = [courses[i], courses[i + 1]]; renderCourses(); save(); }, i === courses.length - 1),
                button('x-lg', 'Remove', () => { courses.splice(i, 1); renderCourses(); save(); }),
            );
        });
        box.replaceChildren(table);
    }

    function locations() {
        const [start, end] = ENDS[vesselType()] || ENDS.horizontal;
        const list = [['shell', 'Shell'], ['start', start], ['end', end]];
        if (horizontal()) list.push(['boot', 'Boot']);
        return list;
    }

    function directionOptions(location) {
        if (location === 'start' || location === 'end') return [];
        if (location === 'boot') return [...directions.compass, 'Bottom'];
        if (horizontal()) return directions.horizontal[form.elements.view_from.value] || directions.horizontal.S;
        return directions.compass;
    }

    function renderNozzles() {
        const box = document.getElementById('nozzle-rows');
        if (!nozzles.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), {
                className: 'vessel-empty', textContent: 'No nozzles yet.',
            }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'vessel-table';
        const head = table.createTHead().insertRow();
        for (const [label, help] of [['Tag', 'As on the client drawing: N1, A, MH-5'], ['Size', 'e.g. 8" (sets how wide it is drawn)'],
            ['On', ''], ['Position', 'Shell: from the start tangent line. Head: off the centre line. Boot: down from the shell.'],
            ['Points', 'Which way it points'], ['', '']]) {
            const th = document.createElement('th');
            th.textContent = label;
            if (help) th.title = help;
            head.append(th);
        }
        const body = table.createTBody();
        nozzles.forEach((row, i) => {
            const tr = body.insertRow();
            const tag = control('input', { type: 'text', value: row.tag || '', maxLength: 12, placeholder: `N${i + 1}` });
            tag.addEventListener('input', () => { row.tag = tag.value; save(); });
            tr.insertCell().append(tag);
            const size = control('input', { type: 'text', value: row.size || '', maxLength: 20, placeholder: '4"' });
            size.classList.add('mono');
            size.addEventListener('input', () => { row.size = size.value; save(); });
            tr.insertCell().append(size);
            const where = control('select', {});
            for (const [value, label] of locations()) where.add(new Option(label, value, false, value === (row.location || 'shell')));
            where.addEventListener('change', () => {
                row.location = where.value;
                const options = directionOptions(row.location);
                if (!options.includes(row.direction)) row.direction = options[0] || '';
                renderNozzles();
                save();
            });
            tr.insertCell().append(where);
            tr.insertCell().append(lengthBox(row.position, v => { row.position = v; }));
            const direction = control('select', {});
            const options = directionOptions(row.location || 'shell');
            direction.disabled = !options.length;
            if (!options.length) direction.add(new Option('Along the axis', ''));
            for (const value of options) direction.add(new Option(value, value, false, value === row.direction));
            if (options.length && row.direction && !options.includes(row.direction)) {
                direction.add(new Option(`${row.direction} (not on this view)`, row.direction, false, true));
                direction.classList.add('is-invalid');
            }
            direction.addEventListener('change', () => { row.direction = direction.value; renderNozzles(); save(); });
            tr.insertCell().append(direction);
            const actions = tr.insertCell();
            actions.className = 'vessel-row-buttons';
            actions.append(
                button('copy', 'Copy this nozzle', () => { nozzles.splice(i + 1, 0, { ...row, tag: '' }); renderNozzles(); save(); }),
                button('x-lg', 'Remove', () => { nozzles.splice(i, 1); renderNozzles(); save(); }),
            );
        });
        box.replaceChildren(table);
    }

    document.querySelectorAll('[data-add-row]').forEach(b => b.addEventListener('click', () => {
        const kind = b.dataset.addRow;
        const last = [...courses].reverse().find(row => row.kind === 'course');
        courses.push(kind === 'flange' ? { kind } : { kind, length: kind === 'cone' ? 24 : (last?.length || 96) });
        renderCourses();
        save();
    }));

    document.getElementById('add-nozzle').addEventListener('click', () => {
        const options = directionOptions('shell');
        nozzles.push({ tag: '', size: '', location: 'shell', position: 0, direction: options[0] || '' });
        renderNozzles();
        save();
        document.querySelector('#nozzle-rows tr:last-child input')?.focus();
    });

    document.getElementById('split-courses').addEventListener('click', () => {
        const count = parseInt(document.getElementById('split-count').value, 10);
        const lengthBox = document.getElementById('split-length');
        let total;
        try { total = parseLength(lengthBox.value); } catch { total = null; }
        lengthBox.classList.toggle('is-invalid', !(total > 0));
        if (!(count > 0) || !(total > 0)) return;
        // Keeps any flanges and the first course's label (an exchanger's channel); the rest are replaced
        const keepStart = courses.findIndex(row => row.kind === 'course' && row.label);
        const head = keepStart >= 0 ? courses.slice(0, keepStart + 1).concat(courses.slice(keepStart + 1).filter(row => row.kind === 'flange').slice(0, 1)) : [];
        const used = head.reduce((sum, row) => sum + (row.kind === 'flange' ? 0 : row.length || 0), 0);
        const each = Math.max(total - used, 1) / count;
        courses = head.concat(Array.from({ length: count }, () => ({ kind: 'course', length: each })));
        renderCourses();
        save();
    });

    // ── type, units, the view ────────────────────────────────────────
    function applyType(initial) {
        const type = vesselType();
        fields.dataset.type = type;
        const [start, end, short] = ENDS[type] || ENDS.horizontal;
        form.querySelector('label[for="id_start_head"]').textContent = start;
        form.querySelector('label[for="id_end_head"]').textContent = end;
        document.querySelector('[data-label-start]').textContent = `Courses from the ${short} end`;
        document.querySelectorAll('[data-label-start-short]').forEach(el => { el.textContent = short; });
        document.querySelectorAll('.horizontal-only').forEach(el => { el.hidden = !horizontal(); });
        if (!initial && form.dataset.new) {   // a new vessel takes the type's usual shape
            const start = typeStarts[type];
            form.elements.start_head.value = start.start_head;
            form.elements.end_head.value = start.end_head;
            form.elements.diameter.value = formatDiameter(start.diameter);
            courses = start.courses.map(row => ({ ...row }));
            renderCourses();
        }
        renderNozzles();
    }

    form.elements.vessel_type.addEventListener('change', () => { applyType(false); save(); });
    form.elements.view_from.addEventListener('change', renderNozzles);

    let units = form.elements.units.value;
    form.elements.units.addEventListener('change', () => {
        const before = units === 'metric';
        units = form.elements.units.value;
        form.querySelectorAll('[data-length]').forEach(input => {
            try {
                const inches = parseLength(input.value, before);
                if (inches === null) return;
                const diameter = ['diameter', 'boot_diameter'].includes(input.dataset.length);
                input.value = diameter ? formatDiameter(inches) : formatLength(inches);
            } catch { /* left as typed */ }
        });
        renderCourses();
        renderNozzles();
    });

    // ── the live drawing ─────────────────────────────────────────────
    let timer = null;
    let request = 0;
    let objectUrl = null;

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(redraw, 350);
    }

    async function redraw() {
        const mine = ++request;
        form.querySelectorAll('.field-cell.has-live-error').forEach(cell => cell.classList.remove('has-error', 'has-live-error'));
        let response;
        try {
            response = await fetch(form.dataset.previewUrl, { method: 'POST', body: new FormData(form) });
        } catch {
            if (mine === request) show('The drawing could not be updated: is the server running?');
            return;
        }
        if (mine !== request) return;
        if (response.ok) {
            const blob = await response.blob();
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = URL.createObjectURL(blob);
            image.src = objectUrl;
            show('');
            return;
        }
        let data = {};
        try { data = await response.json(); } catch { /* not JSON */ }
        const problems = [];
        for (const [name, info] of Object.entries(data.fields || {})) {
            const cell = form.querySelector(`.field-cell[data-field="${name}"]`);
            if (cell) cell.classList.add('has-error', 'has-live-error');
            problems.push(`${info.label || name}: ${info.errors.join(' ')}`);
        }
        show(problems.length ? problems.join(' · ') : (data.error || 'The drawing could not be made.'));
    }

    function show(text) {
        status.textContent = text;
        status.hidden = !text;
    }

    form.addEventListener('input', event => {
        if (event.target.closest('.vessel-rows')) return;   // the rows save (and redraw) themselves
        schedule();
    });
    form.addEventListener('change', event => {
        if (event.target.closest('.vessel-rows')) return;
        schedule();
    });

    window.VesselLengths = { parseLength, formatLength, formatDiameter };
    renderCourses();
    applyType(true);
    if (!image.getAttribute('src')) redraw();
})();
