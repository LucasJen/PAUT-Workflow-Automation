// The Analysis page: pick an .nde file from the working folders and a group, step through its scan
// lines, and look at each one's S-scan (true geometry) and the A-scan under the beam cursor with
// OmniPC's gate readings. Scan lines are stepped by number for now (encoder positions come later).
//
// Gates start as the file's and can be edited (the Gates panel, or dragging them on the A-scan);
// readings always come from the server's checked code with the gates as edited. Reference / measure
// cursors (red / green) in depth (U) and index (I) give the cursor readings. Gates, cursors and the
// reference level are remembered per file and group in this browser.
//
// Whole-file views (P3): the C-scan (scan x line: a gate's amplitude, its peak's depth, or the
// thickness between two gates) and the B-scan (the cursor line's side view) are built once on the
// server (projections.py) and cached; the scan / line / depth cursors are linked across every view.
// Layouts like OmniPC's: A-S, A-S-C, A-B-C-S (remembered per kind of data).
//
// Keys: Left / Right a scan line (Shift: 10), PageUp / PageDown 10 lines, Up / Down the beam
// cursor, + / - soft gain by 1 dB.

(function () {
    const page = document.getElementById('analysis');
    if (!page) return;
    const urls = { files: page.dataset.filesUrl, file: page.dataset.fileUrl, frame: page.dataset.frameUrl,
                   readings: page.dataset.readingsUrl, projections: page.dataset.projectionsUrl,
                   cscan: page.dataset.cscanUrl, bscan: page.dataset.bscanUrl, size: page.dataset.sizeUrl,
                   indications: page.dataset.indicationsUrl, indicationsCsv: page.dataset.indicationsCsvUrl,
                   indication: page.dataset.indicationUrl };
    const $ = id => document.getElementById(id);
    const fileSelect = $('file-select'), fileFilter = $('file-filter'), groupSelect = $('group-select');
    const slider = $('scan-slider'), scanNumber = $('scan-number'), gainInput = $('gain');
    const unitsSelect = $('units'), axisSelect = $('axis'), refInput = $('ref-level');
    const status = $('analysis-status');
    const grid = $('analysis-grid'), layoutSelect = $('layout'), kindSelect = $('cscan-kind');
    const panels = AnalysisLayout(grid);
    const ampPalette = $('amplitude-palette'), rangePalette = $('range-palette');
    for (const [select, kind] of [[ampPalette, 'amplitude'], [rangePalette, 'range']]) {
        select.replaceChildren(...AnalysisPalette.list(kind).map(([v, t]) => new Option(t, v)));
        select.value = localStorage.getItem(`analysisPalette:${kind}`) || 'omnipc';
        if (!select.value) select.value = 'omnipc';
    }
    panels.refresh();
    $('full-screen').addEventListener('click', () => {
        if (document.fullscreenElement) document.exitFullscreen();
        else page.requestFullscreen?.().catch(() => {});
    });

    const READING_NAMES = {
        'A%': 'Peak amplitude in gate A', 'SA^': 'Sound path to the gate A peak', 'DA^': 'Depth of the gate A peak',
        'PA^': 'Gate A peak from the probe', 'ViA^': 'Index position of the gate A peak',
        'B%': 'Peak amplitude in gate B', 'SB^': 'Sound path to the gate B peak', 'DB^': 'Depth of the gate B peak',
        'A/-I/': 'Gate A crossing from the interface (gate I crossing)', 'T(B/-A/)': 'Thickness: gate A crossing to gate B crossing',
        'A dB(r)': 'Gate A peak against the reference level, in dB',
        'U(r)': 'Reference cursor depth', 'U(m)': 'Measure cursor depth', 'U(m-r)': 'Depth between the cursors',
        Scan: 'Scan position of this scan line', Index: 'Index position (the line on a raster, the probe on a weld scan)',
        'S(r)': 'Reference cursor scan position', 'S(m)': 'Measure cursor scan position', 'S(m-r)': 'Scan distance between the cursors',
        Length: 'Indication length from the sizing', Width: 'Indication width (index axis) from the sizing',
        'Peak%': 'Highest gate amplitude of the sized indication', TminZ: 'Least thickness in the zone between the cursors',
        TmaxZ: 'Most thickness in the zone', TavgZ: 'Average thickness in the zone', 'S(TminZ)': 'Scan position of the least thickness',
        'I(TminZ)': 'Index position of the least thickness', 'A%maxZ': 'Highest gate amplitude in the zone',
        'S(A%maxZ)': 'Scan position of the highest amplitude in the zone',
        'I(r)': 'Reference cursor index position', 'I(m)': 'Measure cursor index position', 'I(m-r)': 'Index distance between the cursors',
    };
    const NO_CURSORS = { u_ref: null, u_meas: null, i_ref: null, i_meas: null, s_ref: null, s_meas: null };

    const state = { path: '', group: 0, scan: 0, lateral: 0, gain: 0, info: null, frame: null, values: null,
                    gates: [], gatesEdited: false, cursors: { ...NO_CURSORS }, refLevel: 80, readings: {},
                    cscan: null, cscanGain: 0, cscanRanges: {} };
    const params = new URLSearchParams(location.search);
    let units = localStorage.getItem('analysisUnits') || 'in';
    unitsSelect.value = units;

    const unitLength = () => (units === 'mm' ? 0.001 : 0.0254);
    const format = (m, short = false) => {
        if (m === null || m === undefined || Number.isNaN(m)) return '-';
        const v = m / unitLength();
        return units === 'mm' ? `${v.toFixed(short ? 1 : 2)}${short ? '' : ' mm'}` : `${v.toFixed(short ? 2 : 3)}${short ? '' : ' in'}`;
    };
    const show = text => { status.textContent = text || ''; status.hidden = !text; };

    const sscan = new SScanView($('sscan-stage'), {
        format, unitLength,
        onCursor: lateral => setLateral(lateral),
        onCursors: partial => setCursors(partial),
        onHover: (x, y) => { $('sscan-readout').textContent = x === null ? '' : `Index ${format(x)} · depth ${format(y)}`; },
    });
    let gateSnapshot = null;
    const ascan = new AScanView($('ascan-stage'), {
        format, unitLength,
        onHover: text => { $('ascan-readout').textContent = text || ''; },
        onCursor: (which, depth) => setCursors({ [`u_${which}`]: depth }),
        onGateDragStart: letter => { gateSnapshot = { ...gateByLetter(letter) }; },
        onGateDrag: (letter, { part, dt, threshold }) => {
            const gate = gateByLetter(letter);
            if (!gate || !gateSnapshot) return;
            const minimum = currentGroup().axes[2].resolution;
            if (part === 'move') {
                gate.start = gateSnapshot.start + dt;
                if (threshold !== undefined) gate.threshold = Math.round(threshold);
            } else if (part === 'start') {
                const dtMax = gateSnapshot.length - minimum;
                const d = Math.min(dt, dtMax);
                gate.start = gateSnapshot.start + d;
                gate.length = gateSnapshot.length - d;
            } else {
                gate.length = Math.max(minimum, gateSnapshot.length + dt);
            }
            gatesChanged(20);
        },
        onGateDragEnd: () => { gateSnapshot = null; },
    });

    const CURSOR = '#38bdf8';
    const scanAxis = () => currentGroup().axes[0];
    const scanPosition = i => scanAxis().offset + i * scanAxis().resolution;
    const isRaster = () => currentGroup()?.layout === 'raster';
    const lineY = i => (isRaster() ? currentGroup().axes[1].offset + i * currentGroup().axes[1].resolution : i);
    const lineText = y => {
        const g = currentGroup();
        if (isRaster()) return format(y);
        const beam = g.beams[Math.max(0, Math.min(g.beams.length - 1, Math.round(y)))];
        return beam ? `${beam.refracted_angle}°` : '';
    };
    const cview = new ImageView($('cscan-stage'), {
        formatX: x => format(x, true), formatY: y => (isRaster() ? format(y, true) : lineText(y)),
        xUnit: unitLength, yUnit: () => (isRaster() ? unitLength() : 1),
        onPick: ({ column, row, x, y, inside, event }) => {
            if (event.ctrlKey || event.shiftKey) {   // reference / measure: scan (and index on a raster)
                const which = event.shiftKey ? 'meas' : 'ref';
                setCursors({ [`s_${which}`]: x, ...(isRaster() ? { [`i_${which}`]: y } : {}) });
                return;
            }
            if (!inside) return;
            if (column !== state.scan) setScan(column);
            if (row !== state.lateral) setLateral(row);
        },
        onHover: (x, y, cell) => {
            if (x === null || !state.cscan) { $('cscan-readout').textContent = ''; return; }
            const [col, row] = cell;
            const c = state.cscan;
            const inside = col >= 0 && col < c.scans && row >= 0 && row < c.lines;
            const value = inside ? c.data[col * c.lines + row] : NaN;
            const shown = Number.isNaN(value) ? 'no data'
                : (c.mode === 'amplitude' ? `${(value * Math.pow(10, (state.gain - state.cscanGain) / 20)).toFixed(1)} %` : format(value));
            $('cscan-readout').textContent = `Scan ${format(x)} · ${isRaster() ? 'index ' + format(y) : 'beam ' + lineText(y)} · ${shown}`;
        },
    });
    const bview = new ImageView($('bscan-stage'), {
        formatX: x => format(x, true), formatY: y => format(y, true), xUnit: unitLength, yUnit: unitLength,
        onPick: ({ column, x, y, event, inside }) => {
            if (event.ctrlKey || event.shiftKey) {   // reference / measure: scan and depth
                const which = event.shiftKey ? 'meas' : 'ref';
                setCursors({ [`s_${which}`]: x, [`u_${which}`]: y });
                return;
            }
            if (inside && column !== state.scan) setScan(column);
        },
        onHover: (x, y) => { $('bscan-readout').textContent = x === null ? '' : `Scan ${format(x)} · depth ${format(y)}`; },
    });

    // ── per file / group memory ──
    const memoryKey = () => `analysis:${state.path}:${state.group}`;
    function save() {
        try {
            localStorage.setItem(memoryKey(), JSON.stringify({
                gates: state.gatesEdited ? state.gates : null, cursors: state.cursors, refLevel: state.refLevel,
            }));
        } catch { /* storage full or blocked: nothing to keep */ }
    }
    function restore() {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem(memoryKey()) || 'null'); } catch { saved = null; }
        const g = currentGroup();
        state.gates = saved?.gates || fileGates(g);
        state.gatesEdited = !!saved?.gates;
        state.cursors = { ...NO_CURSORS, ...(saved?.cursors || {}) };
        state.refLevel = saved?.refLevel || 80;
        refInput.value = state.refLevel;
    }
    const fileGates = g => g.gates.map(x => ({
        id: x.id, name: x.name, start: x.start, length: x.length, threshold: x.threshold,
        sync_gate: x.sync_mode === 'GateRelative' ? x.sync_gate : null, trigger: x.trigger || 'Crossing',
    }));
    const letterOf = name => (name || '').trim().split(/\s+/).pop().toUpperCase();
    const gateByLetter = letter => state.gates.find(x => letterOf(x.name) === letter);

    function remember() {
        const q = new URLSearchParams({ path: state.path, group: state.group, scan: state.scan, lateral: state.lateral });
        history.replaceState(null, '', `${location.pathname}?${q}`);
    }

    // ── files and groups ──
    async function loadFiles() {
        const data = await NdeClient.files(urls);
        const byFolder = new Map();
        for (const f of data.files) {
            const key = f.folder === '.' ? f.root : `${f.root}\\${f.folder}`;
            if (!byFolder.has(key)) byFolder.set(key, []);
            byFolder.get(key).push(f);
        }
        fileSelect.replaceChildren(new Option(data.files.length ? 'Pick an .nde file…' : 'No .nde files in the working folders', ''));
        for (const [folder, list] of [...byFolder.entries()].sort()) {
            const group = document.createElement('optgroup');
            group.label = folder;
            for (const f of list.sort((a, b) => a.name.localeCompare(b.name))) {
                group.append(new Option(`${f.name} (${(f.size / 1e6).toFixed(0)} MB)`, f.path));
            }
            fileSelect.append(group);
        }
        const wanted = params.get('path');
        if (wanted && [...fileSelect.options].some(o => o.value === wanted)) {
            fileSelect.value = wanted;
            await openFile(wanted, +params.get('group') || 0, +params.get('scan') || 0, +params.get('lateral') || 0);
        }
    }

    fileFilter.addEventListener('input', () => {
        const words = fileFilter.value.toLowerCase().split(/\s+/).filter(Boolean);
        for (const option of fileSelect.querySelectorAll('optgroup option')) {
            const text = `${option.parentElement.label} ${option.text}`.toLowerCase();
            option.hidden = !words.every(w => text.includes(w));
        }
    });

    function groupLabel(g) {
        if (g.layout === 'unsupported') return `${g.name} - can't be shown (${g.reason})`;
        if (g.layout === 'beams') {
            const angles = g.beams.map(b => b.refracted_angle);
            return `${g.name} · ${g.formation || 'beams'} ${Math.min(...angles)}–${Math.max(...angles)}° · ${g.shape[0]} scan lines`;
        }
        return `${g.name} · ${g.formation || 'linear'} 0° raster · ${g.shape[0]} × ${g.shape[1]}`;
    }

    function showDetails() {
        const s = state.info?.specimen || {};
        $('file-details').textContent = [`NDE ${state.info.version}`, s.thickness ? `part ${format(s.thickness)} thick` : '',
                                         s.material || '', state.info.scan_pattern || ''].filter(Boolean).join(' · ');
    }

    async function openFile(path, group = 0, scan = 0, lateral = 0) {
        show('Opening…');
        try {
            state.info = await NdeClient.file(urls, path);
        } catch (e) {
            show(e.message);
            return;
        }
        state.path = path;
        groupSelect.replaceChildren(...state.info.groups.map(g => {
            const o = new Option(groupLabel(g), g.id);
            o.disabled = g.layout === 'unsupported';
            return o;
        }));
        const usable = state.info.groups.filter(g => g.layout !== 'unsupported');
        if (!usable.length) {
            show("This file has no A-scan data that can be shown (TFM / FMC captures aren't supported).");
            return;
        }
        const chosen = usable.find(g => g.id === group) || usable[0];
        groupSelect.value = chosen.id;
        showDetails();
        show('');
        state.sizing = null;
        await setGroup(chosen.id, scan, lateral);
        loadIndications();
    }

    function applyLayout() {
        const kind = isRaster() ? 'raster' : 'beams';
        const saved = localStorage.getItem(`analysisLayout:${kind}`);
        layoutSelect.value = saved || (kind === 'raster' ? 'A-S-C' : 'A-B-C-S');
        grid.dataset.layout = layoutSelect.value;
        panels.refresh();
    }
    layoutSelect.addEventListener('change', () => {
        grid.dataset.layout = layoutSelect.value;
        panels.refresh();
        try { localStorage.setItem(`analysisLayout:${isRaster() ? 'raster' : 'beams'}`, layoutSelect.value); } catch { /* not kept */ }
        scheduleProjections();
    });

    async function setGroup(id, scan = 0, lateral = 0) {
        state.group = id;
        const g = currentGroup();
        restore();
        applyLayout();
        state.cscan = null;
        cview.clear('');
        bview.clear('');
        fillKinds();
        fillSizeOver();
        scheduleProjections();
        renderGates();
        sscan.setGeometry(g.rays, g.shape[2], state.info.specimen?.thickness);
        sscan.setCursors(state.cursors);
        $('true-geometry').checked = sscan.trueGeometry;
        $('groups-toggle').hidden = otherGroups().length === 0;
        const weld = g.layout === 'beams' ? state.info.weld_outline : null;
        $('weld-toggle').hidden = !(weld && weld.length);
        sscan.setWeld(weld, $('show-weld').checked);
        slider.max = scanNumber.max = g.shape[0] - 1;
        $('scan-count').textContent = `of ${g.shape[0]}`;
        state.lateral = Math.min(lateral, g.shape[1] - 1);
        await setScan(Math.min(scan, g.shape[0] - 1));
    }

    const currentGroup = () => state.info.groups.find(g => g.id === state.group);

    // ── scan line, beam cursor ──
    let frameRequest = 0;
    async function setScan(scan) {
        const g = currentGroup();
        if (!g) return;
        state.scan = Math.max(0, Math.min(g.shape[0] - 1, scan));
        slider.value = scanNumber.value = state.scan;
        $('scan-position').textContent = `= ${format(scanPosition(state.scan))}`;
        linkCursors();
        const mine = ++frameRequest;
        let frame;
        try {
            frame = await NdeClient.frame(urls, state.path, state.group, state.scan);
        } catch (e) {
            show(e.message);
            return;
        }
        if (mine !== frameRequest) return;
        // Raw samples -> % of full screen; lines without data (status bit 1 clear) -> -1
        const scale = g.unit_max / g.raw_max;
        const values = new Float32Array(frame.raw.length);
        for (let i = 0; i < values.length; i++) values[i] = frame.raw[i] * scale;
        if (frame.status) {
            for (let line = 0; line < frame.lateral; line++) {
                if (!(frame.status[line] & 1)) values.fill(-1, line * frame.samples, (line + 1) * frame.samples);
            }
        }
        state.frame = frame;
        state.values = values;
        sscan.setFrame(values, frame.lateral, frame.samples);
        loadOtherGroups();
        setLateral(state.lateral, true);
        remember();
        for (const next of [state.scan + 1, state.scan - 1]) {   // read the neighbours ahead
            if (next >= 0 && next < g.shape[0]) NdeClient.frame(urls, state.path, state.group, next).catch(() => {});
        }
    }

    function setLateral(lateral, force = false) {
        const g = currentGroup();
        if (!g || !state.frame) return;
        lateral = Math.max(0, Math.min(g.shape[1] - 1, lateral));
        if (lateral === state.lateral && !force) return;
        state.lateral = lateral;
        sscan.setCursor(lateral);
        const n = state.frame.samples;
        ascan.set({ values: state.values.subarray(lateral * n, (lateral + 1) * n), ray: g.rays[lateral],
                    period: g.axes[2].resolution, gates: null, cursors: ascanCursors() });
        const beam = g.beams[lateral];
        $('ascan-label').textContent = g.layout === 'beams'
            ? `Beam ${lateral + 1} of ${g.shape[1]} · ${beam.refracted_angle}°`
            : `Index line ${lateral + 1} of ${g.shape[1]} · ${format(beam.v_offset)}`;
        $('sscan-label').textContent = `Scan line ${state.scan + 1}`;
        renderGates();   // its lengths use this beam's velocity
        remember();
        scheduleReadings();
        linkCursors();
        scheduleBscan();
    }

    // ── other groups at the same scan position (the S-scan's All groups) ──
    /** The file's other groups that can be drawn with this one: same layout and scan positions. */
    function otherGroups() {
        const g = currentGroup();
        if (!g) return [];
        return state.info.groups.filter(o => o.id !== g.id && o.layout === g.layout && o.layout !== 'unsupported'
                                             && o.shape[0] === g.shape[0]);
    }
    const percent = (frame, g) => {
        const scale = g.unit_max / g.raw_max;
        const values = new Float32Array(frame.raw.length);
        for (let i = 0; i < values.length; i++) values[i] = frame.raw[i] * scale;
        if (frame.status) {
            for (let line = 0; line < frame.lateral; line++) {
                if (!(frame.status[line] & 1)) values.fill(-1, line * frame.samples, (line + 1) * frame.samples);
            }
        }
        return values;
    };
    let othersRequest = 0;
    async function loadOtherGroups() {
        const others = $('all-groups').checked ? otherGroups() : [];
        const mine = ++othersRequest;
        const scan = state.scan;
        try {
            const extras = await Promise.all(others.map(async o => {
                const frame = await NdeClient.frame(urls, state.path, o.id, scan);
                return { rays: o.rays, samples: frame.samples, lines: frame.lateral, values: percent(frame, o) };
            }));
            if (mine === othersRequest) sscan.setExtras(extras);
        } catch (e) {
            show(e.message);
        }
    }
    $('all-groups').addEventListener('change', loadOtherGroups);
    function nextGroup() {
        const usable = state.info?.groups.filter(o => o.layout !== 'unsupported') || [];
        if (usable.length < 2) return;
        const at = usable.findIndex(o => o.id === state.group);
        const next = usable[(at + 1) % usable.length];
        groupSelect.value = next.id;
        setGroup(next.id, state.scan, state.lateral);
    }

    /** The scan / line / depth cursors on the C-scan and B-scan. */
    function linkCursors() {
        if (!state.info) return;
        const c = state.cursors;
        const index = isRaster() ? [{ value: c.i_ref, colour: '#f87171' }, { value: c.i_meas, colour: '#4ade80' }] : [];
        const scanLines = [{ value: c.s_ref, colour: '#f87171' }, { value: c.s_meas, colour: '#4ade80' },
                           { value: scanPosition(state.scan), colour: CURSOR }];
        const z = zoneBox();
        cview.setCursors({ x: scanLines, y: [{ value: lineY(state.lateral), colour: CURSOR }, ...index],
                           box: z ? z.box : null, marks: z?.mark ? [z.mark] : [] });
        bview.setCursors({ x: scanLines, y: [{ value: c.u_ref, colour: '#f87171' }, { value: c.u_meas, colour: '#4ade80' }] });
    }

    // ── whole-file views ──
    let projectionTimer = null, projectionRequest = 0, bscanTimer = null, bscanRequest = 0;
    const wholeShown = () => grid.dataset.layout !== 'A-S';
    function projectionParams() {
        const q = { path: state.path, group: state.group, gain: state.gain };
        if (state.gatesEdited) q.gates = JSON.stringify(state.gates);
        return q;
    }
    function scheduleProjections(delay = 0) {
        clearTimeout(projectionTimer);
        projectionTimer = setTimeout(loadProjections, delay);
    }
    function progress(fraction) {
        $('cscan-note').innerHTML = fraction === null ? ''
            : `Reading the file… <span class="analysis-progress"><span style="width:${Math.round(fraction * 100)}%"></span></span>`;
    }

    async function loadProjections() {
        if (!state.info || !wholeShown()) return;
        const mine = ++projectionRequest;
        let job;
        try {
            job = await NdeClient.projections(urls, projectionParams());
        } catch (e) {
            cview.clear(e.message);
            return;
        }
        if (mine !== projectionRequest) return;
        if (job.state === 'error') { progress(null); cview.clear(`Couldn't read the whole file: ${job.error}`); return; }
        if (job.state !== 'done') { progress(job.progress || 0); projectionTimer = setTimeout(loadProjections, 400); return; }
        progress(null);
        await loadCscan(mine);
        loadBscan();
    }

    function fillKinds() {
        const g = currentGroup();
        const letters = g.gates.map(x => letterOf(x.name));
        const options = [];
        for (const L of letters) {
            if (L === 'I' && g.synced_to_interface) continue;   // the interface is t = 0 on these files (A−I still works)
            options.push([`${L}:amplitude`, `Gate ${L} amplitude`], [`${L}:depth`, `Gate ${L} peak depth`]);
        }
        if (letters.includes('A') && letters.includes('I')) options.push(['A:thickness:I', 'Thickness A−I (interface to A)']);
        if (letters.includes('A') && letters.includes('B')) options.push(['B:thickness:A', 'Thickness B−A (peak to peak)']);
        kindSelect.replaceChildren(...options.map(([v, t]) => new Option(t, v)));
        const saved = localStorage.getItem(`analysisKind:${isRaster() ? 'raster' : 'beams'}`);
        const has = v => options.some(o => o[0] === v);
        // A 0 deg raster (HydroFORM): interface to A when there's an I gate, else A to B
        const fallback = !isRaster() ? 'A:amplitude' : has('A:thickness:I') ? 'A:thickness:I' : has('B:thickness:A') ? 'B:thickness:A' : 'A:amplitude';
        kindSelect.value = has(saved) ? saved : (has(fallback) ? fallback : (options[0]?.[0] || ''));
    }
    kindSelect.addEventListener('change', () => {
        try { localStorage.setItem(`analysisKind:${isRaster() ? 'raster' : 'beams'}`, kindSelect.value); } catch { /* not kept */ }
        loadCscan(projectionRequest);
    });

    async function loadCscan(request) {
        if (!kindSelect.value) { cview.clear('This group has no gates to make a C-scan from.'); return; }
        const [gate, kind, from] = kindSelect.value.split(':');
        const params = { ...projectionParams(), gate, kind };
        if (from) params.from = from;
        let result;
        try {
            result = await NdeClient.whole(urls.cscan, params, Float32Array);
        } catch (e) {
            cview.clear(e.message);
            return;
        }
        if (request !== projectionRequest) return;
        if (result.building) { scheduleProjections(400); return; }
        const scans = +result.header('X-Scans'), lines = +result.header('X-Lines');
        const mode = kind === 'amplitude' ? 'amplitude' : 'range';
        // Thickness runs over the file's own expected range, like OmniPC's palette; else the data's
        const fileRange = kind === 'thickness' ? currentGroup().thickness_range : null;
        const auto = fileRange ? [fileRange[0], fileRange[1]] : [+result.header('X-Min'), +result.header('X-Max')];
        const range = state.cscanRanges[kindSelect.value] || auto;
        const g = currentGroup();
        const keep = !!state.cscan && state.cscan.scans === scans && state.cscan.lines === lines;
        state.cscan = { data: result.data, scans, lines, mode };
        state.cscanGain = state.gain;
        cview.setGain(0);
        cview.setImage(result.data, scans, lines, {
            transpose: true, mode, range, keepView: keep, smooth: !isRaster(),
            axes: { x0: g.axes[0].offset, dx: g.axes[0].resolution, y0: lineY(0), dy: isRaster() ? g.axes[1].resolution : 1 },
        });
        renderReadings();
        $('cscan-range').hidden = mode === 'amplitude';
        if (mode !== 'amplitude') {
            $('cscan-min').value = (range[0] / unitLength()).toFixed(3);
            $('cscan-max').value = (range[1] / unitLength()).toFixed(3);
        }
        linkCursors();
    }
    for (const id of ['cscan-min', 'cscan-max']) {
        $(id).addEventListener('change', () => {
            const lo = parseFloat($('cscan-min').value) * unitLength(), hi = parseFloat($('cscan-max').value) * unitLength();
            if (!(Number.isFinite(lo) && Number.isFinite(hi) && hi > lo)) return;
            state.cscanRanges[kindSelect.value] = [lo, hi];
            cview.setRange([lo, hi]);
        });
    }

    function scheduleBscan() {
        clearTimeout(bscanTimer);
        bscanTimer = setTimeout(loadBscan, 80);
    }

    async function loadBscan() {
        if (!state.info || grid.dataset.layout !== 'A-B-C-S') return;
        const mine = ++bscanRequest;
        const line = state.lateral;
        let result;
        try {
            result = await NdeClient.whole(urls.bscan, { ...projectionParams(), line }, Uint8Array);
        } catch (e) {
            bview.clear(e.message);
            return;
        }
        if (mine !== bscanRequest) return;
        if (result.building) { scheduleProjections(400); return; }
        const scans = +result.header('X-Scans'), bins = +result.header('X-Bins');
        const factor = +result.header('X-Factor'), full = +result.header('X-Full');
        const values = new Float32Array(result.data.length);
        for (let i = 0; i < values.length; i++) values[i] = result.data[i] * full / 255;
        const g = currentGroup(), ray = g.rays[line];
        bview.setImage(values, scans, bins, {
            transpose: true, mode: 'amplitude', keepView: !!bview.hasImage, smooth: true,
            axes: { x0: g.axes[0].offset, dx: g.axes[0].resolution,
                    y0: (ray.sp_start + (factor - 1) / 2 * ray.sp_step) * ray.dz, dy: factor * ray.sp_step * ray.dz },
        });
        bview.setGain(state.gain);
        $('bscan-label').textContent = g.layout === 'beams' ? `Beam ${line + 1} · ${g.beams[line].refracted_angle}°` : `Index line ${line + 1}`;
        linkCursors();
    }

    // ── cursors ──
    const ascanCursors = () => ({ ref: state.cursors.u_ref, meas: state.cursors.u_meas });
    function setCursors(partial) {
        Object.assign(state.cursors, partial);
        sscan.setCursors(state.cursors);
        linkCursors();
        ascan.set({ cursors: ascanCursors() });
        renderReadings();
        save();
    }
    $('clear-cursors').addEventListener('click', () => { state.sizing = null; $('size-note').textContent = ''; setCursors({ ...NO_CURSORS }); });

    // ── zone between the scan (and, on a raster, index) cursors ──
    const has = v => v !== null && v !== undefined && Number.isFinite(v);
    /** {box, stats, mark} of the C-scan zone between the cursors, or null. */
    function zoneBox() {
        const c = state.cursors, cs = state.cscan, g = currentGroup();
        if (!g || !cs || !has(c.s_ref) || !has(c.s_meas)) return null;
        const ax = g.axes[0];
        const col = x => Math.round((x - ax.offset) / ax.resolution);
        const c0 = Math.max(0, Math.min(col(c.s_ref), col(c.s_meas))), c1 = Math.min(cs.scans - 1, Math.max(col(c.s_ref), col(c.s_meas)));
        let r0 = 0, r1 = cs.lines - 1;
        if (isRaster() && has(c.i_ref) && has(c.i_meas)) {
            const ay = g.axes[1];
            const row = y => Math.round((y - ay.offset) / ay.resolution);
            r0 = Math.max(0, Math.min(row(c.i_ref), row(c.i_meas)));
            r1 = Math.min(cs.lines - 1, Math.max(row(c.i_ref), row(c.i_meas)));
        }
        if (c1 < c0 || r1 < r0) return null;
        let min = Infinity, max = -Infinity, sum = 0, count = 0, minAt = null, maxAt = null;
        for (let i = c0; i <= c1; i++) {
            for (let j = r0; j <= r1; j++) {
                const v = cs.data[i * cs.lines + j];
                if (Number.isNaN(v)) continue;
                sum += v; count++;
                if (v < min) { min = v; minAt = [i, j]; }
                if (v > max) { max = v; maxAt = [i, j]; }
            }
        }
        const dy = isRaster() ? g.axes[1].resolution : 1;
        const box = { x0: scanPosition(c0) - ax.resolution / 2, x1: scanPosition(c1) + ax.resolution / 2,
                      y0: lineY(r0) - dy / 2, y1: lineY(r1) + dy / 2 };
        if (!count) return { box, stats: null, mark: null };
        const at = cs.mode === 'amplitude' ? maxAt : minAt;
        return { box, stats: { min, max, mean: sum / count, count, minAt, maxAt },
                 mark: { x: scanPosition(at[0]), y: lineY(at[1]), colour: '#facc15' } };
    }

    // ── gates ──
    const halfVelocity = () => (currentGroup()?.beams[state.lateral]?.velocity || 0) / 2;   // sound path per s
    const gateLength = t => format(t * halfVelocity(), true);

    function renderGates() {
        const g = currentGroup();
        const box = $('gate-rows');
        if (!g) return;
        if (!state.gates.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), { className: 'analysis-note', textContent: 'This group has no gates.' }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'analysis-gates';
        const head = table.createTHead().insertRow();
        for (const [label, help] of [['', ''], ['Start', 'Sound path from the pulse, or after the sync gate\'s crossing'],
            ['Width', 'Sound path'], ['Thr %', 'Threshold, % of full screen'], ['Sync', 'What the gate starts from']]) {
            head.append(Object.assign(document.createElement('th'), { textContent: label, title: help }));
        }
        const body = table.createTBody();
        for (const gate of state.gates) {
            const letter = letterOf(gate.name);
            const tr = body.insertRow();
            tr.insertCell().append(Object.assign(document.createElement('span'), { className: `gate-letter gate-${letter}`, textContent: letter }));
            const number = (value, onChange) => {
                const input = Object.assign(document.createElement('input'), { type: 'text', inputMode: 'decimal', value,
                                                                              className: 'form-control form-control-sm mono' });
                input.addEventListener('change', () => {
                    const v = parseFloat(input.value);
                    if (Number.isFinite(v)) onChange(v);
                    gatesChanged();
                });
                return input;
            };
            tr.insertCell().append(number(gateLength(gate.start), v => { gate.start = v * unitLength() / halfVelocity(); }));
            tr.insertCell().append(number(gateLength(gate.length), v => { if (v > 0) gate.length = v * unitLength() / halfVelocity(); }));
            tr.insertCell().append(number(String(Math.round(gate.threshold * 10) / 10), v => { gate.threshold = Math.max(0, Math.min(100, v)); }));
            const sync = Object.assign(document.createElement('select'), { className: 'form-select form-select-sm' });
            sync.add(new Option('Pulse', ''));
            for (const other of state.gates) {
                if (other !== gate) sync.add(new Option(letterOf(other.name), other.id, false, gate.sync_gate === other.id));
            }
            if (gate.sync_gate === null) sync.value = '';
            sync.addEventListener('change', () => { gate.sync_gate = sync.value === '' ? null : +sync.value; gatesChanged(); });
            tr.insertCell().append(sync);
        }
        box.replaceChildren(table);
        $('gates-edited').hidden = !state.gatesEdited;
    }

    function gatesChanged(delay = 60) {
        state.gatesEdited = true;
        save();
        if (!document.activeElement?.closest('#gate-rows')) renderGates();
        $('gates-edited').hidden = false;
        scheduleReadings(delay);
        scheduleProjections(700);   // the C-scan follows the gates once they settle
    }

    $('reset-gates').addEventListener('click', () => {
        state.gates = fileGates(currentGroup());
        state.gatesEdited = false;
        save();
        renderGates();
        scheduleReadings();
        scheduleProjections();
    });

    // ── readings ──
    let readingsTimer = null, readingsRequest = 0;
    function scheduleReadings(delay = 60) {
        clearTimeout(readingsTimer);
        readingsTimer = setTimeout(loadReadings, delay);
    }

    async function loadReadings() {
        const mine = ++readingsRequest;
        const query = { path: state.path, group: state.group, scan: state.scan, lateral: state.lateral, gain: state.gain };
        if (state.gatesEdited) query.gates = JSON.stringify(state.gates);
        let data;
        try {
            data = await NdeClient.readings(urls, query);
        } catch (e) {
            show(e.message);
            return;
        }
        if (mine !== readingsRequest) return;
        show('');
        ascan.set({ gates: data.gates });
        state.readings = data.readings;
        state.readingsNote = data.note || '';
        renderReadings();
    }

    function renderReadings() {
        const list = $('readings');
        const rows = [];
        const add = (name, text, section = false) => {
            if (section) rows.push(Object.assign(document.createElement('div'), { className: 'analysis-reading-section', textContent: name }));
            else {
                rows.push(Object.assign(document.createElement('dt'), { textContent: name, title: READING_NAMES[name] || '' }));
                rows.push(Object.assign(document.createElement('dd'), { className: 'mono', textContent: text }));
            }
        };
        const values = state.readings || {};
        if (state.info && currentGroup()) {
            add('Scan', format(scanPosition(state.scan)));
            add('Index', format(isRaster() ? lineY(state.lateral) : (state.info.probe?.v_offset ?? 0)));
        }
        for (const [name, value] of Object.entries(values)) {
            add(name, name.includes('%') ? `${value.toFixed(1)} %` : format(value));
            if (name === 'A%' && value > 0 && state.refLevel > 0) {
                const db = 20 * Math.log10(value / state.refLevel);
                add('A dB(r)', `${db >= 0 ? '+' : ''}${db.toFixed(1)} dB`);
            }
        }
        if (!Object.keys(values).length) rows.push(Object.assign(document.createElement('dd'), { className: 'analysis-note', textContent: state.readingsNote || 'No gate signal on this line.' }));
        const c = state.cursors;
        if (state.sizing) {
            const r = state.sizing;
            add(`Sizing (${r.method === 'threshold' ? 'threshold' : '−' + r.method + ' dB'})`, '', true);
            add(r.axis === 'index' ? 'Width' : 'Length', format(r.length));
            add('Peak%', `${r.peak_amplitude.toFixed(1)} %`);
        }
        if ([c.u_ref, c.u_meas, c.i_ref, c.i_meas, c.s_ref, c.s_meas].some(has)) {
            add('Cursors', '', true);
            if (has(c.s_ref)) add('S(r)', format(c.s_ref));
            if (has(c.s_meas)) add('S(m)', format(c.s_meas));
            if (has(c.s_ref) && has(c.s_meas)) add('S(m-r)', format(c.s_meas - c.s_ref));
            if (has(c.u_ref)) add('U(r)', format(c.u_ref));
            if (has(c.u_meas)) add('U(m)', format(c.u_meas));
            if (has(c.u_ref) && has(c.u_meas)) add('U(m-r)', format(c.u_meas - c.u_ref));
            if (has(c.i_ref)) add('I(r)', format(c.i_ref));
            if (has(c.i_meas)) add('I(m)', format(c.i_meas));
            if (has(c.i_ref) && has(c.i_meas)) add('I(m-r)', format(c.i_meas - c.i_ref));
        }
        const z = zoneBox();
        if (z && z.stats) {
            const s = z.stats;
            add('Zone', '', true);
            if (state.cscan.mode === 'amplitude') {
                add('A%maxZ', `${s.max.toFixed(1)} %`);
                add('S(A%maxZ)', format(scanPosition(s.maxAt[0])));
            } else {
                add('TminZ', format(s.min));
                add('S(TminZ)', format(scanPosition(s.minAt[0])));
                if (isRaster()) add('I(TminZ)', format(lineY(s.minAt[1])));
                add('TmaxZ', format(s.max));
                add('TavgZ', format(s.mean));
            }
        }
        list.replaceChildren(...rows);
        state.shownReadings = snapshot();
    }

    /** Every reading on show, SI (for an indication): the gate readings, dB, cursors, sizing, zone. */
    function snapshot() {
        const out = { ...(state.readings || {}) };
        const a = out['A%'];
        if (a > 0 && state.refLevel > 0) out['A dB(r)'] = 20 * Math.log10(a / state.refLevel);
        const c = state.cursors;
        for (const [key, name] of [['s', 'S'], ['u', 'U'], ['i', 'I']]) {
            if (has(c[`${key}_ref`])) out[`${name}(r)`] = c[`${key}_ref`];
            if (has(c[`${key}_meas`])) out[`${name}(m)`] = c[`${key}_meas`];
            if (has(c[`${key}_ref`]) && has(c[`${key}_meas`])) out[`${name}(m-r)`] = c[`${key}_meas`] - c[`${key}_ref`];
        }
        if (state.sizing) {
            out[state.sizing.axis === 'index' ? 'Width' : 'Length'] = state.sizing.length;
            out['Peak%'] = state.sizing.peak_amplitude;
        }
        const z = zoneBox();
        if (z && z.stats && state.cscan) {
            if (state.cscan.mode === 'amplitude') out['A%maxZ'] = z.stats.max;
            else Object.assign(out, { TminZ: z.stats.min, TmaxZ: z.stats.max, TavgZ: z.stats.mean,
                                      'S(TminZ)': scanPosition(z.stats.minAt[0]), ...(isRaster() ? { 'I(TminZ)': lineY(z.stats.minAt[1]) } : {}) });
        }
        return out;
    }

    // ── sizing ──
    function fillSizeOver() {
        const options = isRaster()
            ? [['scan:current', 'Length along the scan'], ['index:current', 'Width along the index']]
            : [['scan:all', 'Length (all beams)'], ['scan:current', 'Length (this beam)']];
        $('size-over').replaceChildren(...options.map(([v, t]) => new Option(t, v)));
    }

    async function sizeNow() {
        if (!state.info) return;
        const [axis, lines] = $('size-over').value.split(':');
        const note = $('size-note');
        note.textContent = 'Sizing…';
        let response, data;
        try {
            response = await fetch(`${urls.size}?${new URLSearchParams({ ...projectionParams(), scan: state.scan, lateral: state.lateral,
                                                                          axis, lines, method: $('size-method').value, gate: 'A' })}`);
            data = await response.json();
        } catch {
            note.textContent = "Couldn't size: is the server running?";
            return;
        }
        if (response.status === 409) { note.textContent = 'The C-scan data is still being built - try again in a moment.'; scheduleProjections(); return; }
        if (!response.ok) { note.textContent = data.error || "Couldn't size here."; return; }
        state.sizing = data;
        note.textContent = '';
        const which = axis === 'index' ? 'i' : 's';
        setCursors({ [`${which}_ref`]: data.start, [`${which}_meas`]: data.end });
    }
    $('size-now').addEventListener('click', sizeNow);

    // ── indications ──
    const csrf = () => (document.cookie.split('; ').find(c => c.startsWith('csrftoken=')) || '').split('=')[1] || '';
    async function send(url, method, body) {
        const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrf()) },
                                            body: body === undefined ? undefined : JSON.stringify(body) });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
        return data;
    }
    const indicationUrl = id => urls.indication.replace('/0.json', `/${id}.json`);

    async function loadIndications() {
        if (!state.path) return;
        try {
            const data = await NdeClient.readings({ readings: urls.indications }, { path: state.path });
            state.indications = data.indications;
        } catch (e) {
            state.indications = [];
        }
        renderIndications();
        $('export-indications').href = `${urls.indicationsCsv}?${new URLSearchParams({ path: state.path, units })}`;
    }

    async function addIndication() {
        if (!state.info) return;
        const g = currentGroup();
        try {
            await send(urls.indications, 'POST', {
                path: state.path, group: state.group, scan: state.scan, lateral: state.lateral,
                scan_position: scanPosition(state.scan), index_position: isRaster() ? lineY(state.lateral) : (state.info.probe?.v_offset ?? null),
                angle: g.layout === 'beams' ? g.beams[state.lateral].refracted_angle : null, gain: state.gain,
                readings: snapshot(), cursors: state.cursors, sizing: state.sizing || {},
            });
        } catch (e) {
            show(e.message);
            return;
        }
        showTab('indications');
        loadIndications();
    }

    function renderIndications() {
        const list = state.indications || [];
        $('indication-count').textContent = list.length ? `(${list.length})` : '';
        const box = $('indication-rows');
        if (!list.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), { className: 'analysis-note',
                textContent: 'No indications yet. Size the indication, then Add indication (N) to keep its readings.' }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'analysis-indication-table';
        const head = table.createTHead().insertRow();
        for (const h of ['#', 'Scan', isRaster() ? 'Index' : 'Angle', 'A%', 'Depth', 'Length', 'Comment', '']) {
            head.append(Object.assign(document.createElement('th'), { textContent: h }));
        }
        const body = table.createTBody();
        for (const item of list) {
            const tr = body.insertRow();
            if (item.scan === state.scan && item.lateral === state.lateral) tr.className = 'is-current';
            const r = item.readings || {};
            const depth = r['DA^'] ?? r['A/-I/'] ?? r['TminZ'];
            const length = r.Length ?? r.Width ?? r['S(m-r)'];
            const cells = [item.number, format(item.scan_position, true),
                           isRaster() ? format(item.index_position, true) : (item.angle === null ? '-' : `${item.angle}°`),
                           r['A%'] === undefined ? '-' : r['A%'].toFixed(1), depth === undefined ? '-' : format(depth, true),
                           length === undefined ? '-' : format(Math.abs(length), true)];
            for (const text of cells) tr.insertCell().textContent = text;
            const comment = Object.assign(document.createElement('input'), { type: 'text', className: 'form-control', value: item.comment || '',
                                                                            placeholder: 'Comment' });
            comment.addEventListener('click', e => e.stopPropagation());
            comment.addEventListener('change', () => send(indicationUrl(item.id), 'POST', { comment: comment.value })
                .then(saved => { item.comment = saved.comment; }).catch(e => show(e.message)));
            tr.insertCell().append(comment);
            const remove = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-sm btn-secondary',
                                                                           title: 'Delete this indication', innerHTML: '<i class="bi bi-x-lg"></i>' });
            remove.addEventListener('click', async e => {
                e.stopPropagation();
                try { await send(indicationUrl(item.id), 'DELETE'); } catch (err) { show(err.message); return; }
                loadIndications();
            });
            tr.insertCell().append(remove);
            tr.addEventListener('click', () => goTo(item));
        }
        box.replaceChildren(table);
    }

    async function goTo(item) {
        if (item.group !== state.group) await setGroup(item.group, item.scan, item.lateral);
        state.sizing = item.sizing && item.sizing.length !== undefined ? item.sizing : null;
        setCursors({ ...NO_CURSORS, ...(item.cursors || {}) });
        await setScan(item.scan);
        setLateral(item.lateral, true);
        renderIndications();
    }

    $('add-indication').addEventListener('click', addIndication);

    // ── picture of the views ──
    /** The visible views as laid out on screen, their titles, and the readings, saved as a PNG. */
    function saveImage() {
        if (!state.info) return;
        const ratio = window.devicePixelRatio || 1;
        const origin = grid.getBoundingClientRect();
        const panelsShown = [...grid.querySelectorAll('.analysis-panel')]
            .filter(p => !p.classList.contains('analysis-readings') && p.offsetParent !== null);
        const width = Math.max(...panelsShown.map(p => p.getBoundingClientRect().right)) - origin.left;
        const height = Math.max(...panelsShown.map(p => p.getBoundingClientRect().bottom)) - origin.top;
        const side = 240, title = 26;
        const out = document.createElement('canvas');
        out.width = Math.round((width + side) * ratio);
        out.height = Math.round((height + title) * ratio);
        const ctx = out.getContext('2d');
        ctx.scale(ratio, ratio);
        ctx.fillStyle = '#0f1115';
        ctx.fillRect(0, 0, width + side, height + title);
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '600 13px Inter, Arial, sans-serif';
        const g = currentGroup();
        ctx.fillText(`${state.info.path.split(/[\\/]/).pop()} · ${g.name} · scan line ${state.scan + 1} (${format(scanPosition(state.scan))}) · gain ${state.gain.toFixed(1)} dB`, 8, 17);
        for (const panel of panelsShown) {
            const box = panel.getBoundingClientRect();
            const x = box.left - origin.left, y = box.top - origin.top + title;
            const head = panel.querySelector('.analysis-panel-head');
            ctx.fillStyle = '#1a1d24';
            ctx.fillRect(x, y, box.width, 22);
            ctx.fillStyle = '#e2e8f0';
            ctx.font = '600 12px Inter, Arial, sans-serif';
            const label = [...head.querySelectorAll(':scope > span')].map(s => s.textContent.trim()).filter(Boolean).join('  ');
            ctx.fillText(label, x + 6, y + 15);
            const stage = panel.querySelector('.analysis-stage');
            const stageBox = stage.getBoundingClientRect();
            for (const canvas of stage.querySelectorAll('canvas')) {
                ctx.drawImage(canvas, stageBox.left - origin.left, stageBox.top - origin.top + title, stageBox.width, stageBox.height);
            }
        }
        // The readings down the right
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '600 12px Inter, Arial, sans-serif';
        let ry = title + 16;
        ctx.fillText('Readings', width + 12, ry);
        ctx.font = '12px Inter, Arial, sans-serif';
        for (const [name, value] of Object.entries(state.shownReadings || {})) {
            ry += 17;
            if (ry > height + title - 4) break;
            const text = name.includes('%') ? `${value.toFixed(1)} %` : name.includes('dB') ? `${value.toFixed(1)} dB` : format(value);
            ctx.fillStyle = '#94a3b8';
            ctx.fillText(name, width + 12, ry);
            ctx.fillStyle = '#e2e8f0';
            ctx.textAlign = 'right';
            ctx.fillText(text, width + side - 10, ry);
            ctx.textAlign = 'left';
        }
        out.toBlob(blob => {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            const stem = state.info.path.split(/[\\/]/).pop().replace(/\.nde$/i, '');
            a.download = `${stem} - scan ${state.scan + 1}.png`;
            document.body.append(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        }, 'image/png');
    }
    $('save-image').addEventListener('click', saveImage);

    function showTab(name) {
        document.querySelectorAll('.analysis-tab').forEach(t => t.classList.toggle('is-active', t.dataset.tab === name));
        document.querySelectorAll('[data-tab-body]').forEach(b => { b.hidden = b.dataset.tabBody !== name; });
    }
    document.querySelectorAll('.analysis-tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.tab)));

    // ── controls ──
    fileSelect.addEventListener('change', () => { if (fileSelect.value) openFile(fileSelect.value); });
    groupSelect.addEventListener('change', () => setGroup(+groupSelect.value, state.scan, state.lateral));
    slider.addEventListener('input', () => setScan(+slider.value));
    scanNumber.addEventListener('change', () => setScan(+scanNumber.value));
    $('scan-prev').addEventListener('click', () => setScan(state.scan - 1));
    $('scan-next').addEventListener('click', () => setScan(state.scan + 1));

    function setGain(db) {
        state.gain = Math.round(Math.max(-40, Math.min(40, db)) * 10) / 10;
        gainInput.value = state.gain.toFixed(1);
        sscan.setGain(state.gain);
        ascan.setGain(state.gain);
        bview.setGain(state.gain);
        cview.setGain(state.gain - state.cscanGain);   // straight away; the rebuilt C-scan follows
        scheduleReadings();
        scheduleProjections(800);
    }
    gainInput.addEventListener('change', () => setGain(parseFloat(gainInput.value) || 0));
    $('gain-down').addEventListener('click', () => setGain(state.gain - 1));
    $('gain-up').addEventListener('click', () => setGain(state.gain + 1));
    refInput.addEventListener('change', () => {
        const v = parseFloat(refInput.value);
        state.refLevel = Number.isFinite(v) && v > 0 ? v : 80;
        refInput.value = state.refLevel;
        save();
        renderReadings();
    });
    unitsSelect.addEventListener('change', () => {
        units = unitsSelect.value;
        localStorage.setItem('analysisUnits', units);
        sscan.drawOverlay();
        ascan.draw();
        if (state.info) {
            showDetails(); renderGates(); renderReadings(); setLateral(state.lateral, true);
            $('scan-position').textContent = `= ${format(scanPosition(state.scan))}`;
            cview.drawOverlay(); bview.drawOverlay();
            if (state.cscan && state.cscan.mode !== 'amplitude') loadCscan(projectionRequest);
        }
    });
    axisSelect.addEventListener('change', () => ascan.setAxis(axisSelect.value));
    $('sscan-fit').addEventListener('click', () => { sscan.view = null; sscan.draw(); });
    $('true-geometry').addEventListener('change', e => sscan.setTrueGeometry(e.target.checked));
    $('show-weld').addEventListener('change', e => { sscan.showWeld = e.target.checked; sscan.drawOverlay(); });

    document.addEventListener('keydown', e => {
        if (!state.info || e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
        const big = e.shiftKey ? 10 : 1;
        const actions = {
            ArrowLeft: () => setScan(state.scan - big), ArrowRight: () => setScan(state.scan + big),
            PageUp: () => setScan(state.scan - 10), PageDown: () => setScan(state.scan + 10),
            ArrowUp: () => setLateral(state.lateral - 1), ArrowDown: () => setLateral(state.lateral + 1),
            '+': () => setGain(state.gain + 1), '=': () => setGain(state.gain + 1), '-': () => setGain(state.gain - 1),
            l: sizeNow, L: sizeNow, n: addIndication, N: addIndication, g: nextGroup, G: nextGroup, p: saveImage, P: saveImage,
        };
        if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
    });

    function applyPalettes() {
        sscan.setPalette(ampPalette.value);
        bview.setPalettes({ amplitude: ampPalette.value });
        cview.setPalettes({ amplitude: ampPalette.value, range: rangePalette.value });
    }
    for (const [select, kind] of [[ampPalette, 'amplitude'], [rangePalette, 'range']]) {
        select.addEventListener('change', () => {
            try { localStorage.setItem(`analysisPalette:${kind}`, select.value); } catch { /* not kept */ }
            applyPalettes();
        });
    }
    applyPalettes();
    page.views = { sscan, ascan, cview, bview };   // for checking the page in a test browser
    loadFiles().catch(e => show(e.message));
})();
