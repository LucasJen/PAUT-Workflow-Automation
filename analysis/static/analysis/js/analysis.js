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
                   indication: page.dataset.indicationUrl, reportTargets: page.dataset.reportTargetsUrl,
                   reportPreview: page.dataset.reportPreviewUrl, weldOutline: page.dataset.weldOutlineUrl, reportSend: page.dataset.reportSendUrl };
    const $ = id => document.getElementById(id);
    const fileList = $('file-list'), fileFilter = $('file-filter'), groupSelect = $('group-select');
    const shell = window.AnalysisShell;
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
    shell.onChange(() => requestAnimationFrame(panels.fit));   // a panel opened / closed, the readings shown / hidden

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
        onWeldShift: (shift, done) => weldShifted(shift, done),
        onHover: (x, y) => {
            if (x === null) { $('sscan-readout').textContent = ''; return; }
            let value = '';
            const g = currentGroup();
            if (g && state.values) {
                const line = sscan.pick([x, y]);
                const r = g.rays[line];
                const len2 = r.dv * r.dv + r.dz * r.dz || 1;
                const sp = ((x - r.v0) * r.dv + y * r.dz) / len2;
                const sample = Math.round((sp - r.sp_start) / r.sp_step);
                const n = state.frame.samples;
                if (sample >= 0 && sample < n) {
                    const v = state.values[line * n + sample];
                    value = v < 0 ? ' · no data' : ` · ${(v * Math.pow(10, state.gain / 20)).toFixed(1)} %`;
                }
            }
            $('sscan-readout').textContent = `Index ${format(x)} · depth ${format(y)}${value}`;
        },
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
    /** The scan line and beam / index line at a C-scan position (from the file's axes, not the drawn cells). */
    const cscanCell = (x, y) => {
        const g = currentGroup();
        const col = Math.round((x - g.axes[0].offset) / g.axes[0].resolution);
        const row = isRaster() ? Math.round((y - g.axes[1].offset) / g.axes[1].resolution) : Math.round(y);
        return [col, row, col >= 0 && col < g.shape[0] && row >= 0 && row < g.shape[1]];
    };
    const cview = new ImageView($('cscan-stage'), {
        formatX: x => format(x, true), formatY: y => (isRaster() ? format(y, true) : lineText(y)),
        formatRange: v => format(v, true),
        xUnit: unitLength, yUnit: () => (isRaster() ? unitLength() : 1),
        onPick: ({ x, y, event }) => {
            const [column, row, inside] = cscanCell(x, y);
            if (event.ctrlKey || event.shiftKey) {   // reference / measure: scan (and index on a raster)
                const which = event.shiftKey ? 'meas' : 'ref';
                setCursors({ [`s_${which}`]: x, ...(isRaster() ? { [`i_${which}`]: y } : {}) });
                return;
            }
            if (!inside) return;
            if (column !== state.scan) setScan(column);
            if (row !== state.lateral) setLateral(row);
        },
        onHover: (x, y) => {
            if (x === null || !state.cscan) { $('cscan-readout').textContent = ''; return; }
            const [col, row] = cscanCell(x, y);
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
        onPick: ({ x, y, event }) => {
            const [column] = cscanCell(x, 0);
            const inside = column >= 0 && column < currentGroup().shape[0];
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
    let allFiles = [];
    async function loadFiles() {
        const data = await NdeClient.files(urls);
        allFiles = data.files;
        renderFiles();
        const known = new Set(allFiles.map(f => f.path));
        const wanted = params.get('path') || recentFiles().find(p => known.has(p));
        if (wanted && known.has(wanted)) {
            await openFile(wanted, +params.get('group') || 0, +params.get('scan') || 0, +params.get('lateral') || 0);
        } else {
            shell.open('files');
            fileFilter.focus();
        }
    }

    /** The Files panel: recent files first, then every folder's files; the filter matches folder and name words. */
    function renderFiles() {
        const words = fileFilter.value.toLowerCase().split(/\s+/).filter(Boolean);
        // Shown and matched below the working folder: its own name, then the sub-folders
        const rootName = f => f.root.split(/[\\/]/).filter(Boolean).pop();
        const folderOf = f => (f.folder === '.' ? rootName(f) : `${rootName(f)} › ${f.folder.split(/[\\/]/).join(' › ')}`);
        const matches = f => words.every(w => `${f.folder === '.' ? '' : f.folder} ${f.name}`.toLowerCase().includes(w));
        const item = (f, meta) => {
            const b = Object.assign(document.createElement('button'), { type: 'button', className: 'analysis-file-item', title: f.path });
            b.dataset.path = f.path;
            b.classList.toggle('is-current', f.path === state.path);
            b.append(Object.assign(document.createElement('span'), { className: 'name', textContent: f.name }),
                     Object.assign(document.createElement('span'), { className: 'meta', textContent: meta }));
            b.addEventListener('click', () => openFile(f.path));
            return b;
        };
        const heading = text => Object.assign(document.createElement('div'), { className: 'analysis-file-folder', textContent: text, title: text });
        const out = [];
        const byPath = new Map(allFiles.map(f => [f.path, f]));
        const recent = recentFiles().map(p => byPath.get(p)).filter(f => f && matches(f));
        if (recent.length) {
            out.push(heading('Recent'));
            for (const f of recent) out.push(item(f, f.folder === '.' ? rootName(f) : f.folder.split(/[\\/]/).pop()));
        }
        const byFolder = new Map();
        for (const f of allFiles.filter(matches)) {
            if (!byFolder.has(folderOf(f))) byFolder.set(folderOf(f), []);
            byFolder.get(folderOf(f)).push(f);
        }
        for (const [folder, list] of [...byFolder.entries()].sort()) {
            out.push(heading(folder));
            for (const f of list.sort((a, b) => a.name.localeCompare(b.name))) out.push(item(f, `${(f.size / 1e6).toFixed(0)} MB`));
        }
        if (!out.length) {
            out.push(Object.assign(document.createElement('p'), { className: 'analysis-note',
                textContent: allFiles.length ? 'No files match.' : 'No .nde files in the working folders.' }));
        }
        fileList.replaceChildren(...out);
    }
    fileFilter.addEventListener('input', renderFiles);
    fileFilter.addEventListener('keydown', e => {   // Enter opens the first match
        if (e.key !== 'Enter') return;
        const first = fileList.querySelector('.analysis-file-item');
        if (first) first.click();
    });
    $('file-button').addEventListener('click', () => { shell.toggle('files'); if (shell.current === 'files') fileFilter.focus(); });

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

    function recentFiles() {
        try { return JSON.parse(localStorage.getItem('analysisRecent') || '[]'); } catch { return []; }
    }
    function rememberRecent(path) {
        const list = [path, ...recentFiles().filter(p => p !== path)].slice(0, 8);
        try { localStorage.setItem('analysisRecent', JSON.stringify(list)); } catch { /* not kept */ }
    }

    async function openFile(path, group = 0, scan = 0, lateral = 0) {
        show('Opening…');
        grid.classList.remove('is-empty');
        try {
            state.info = await NdeClient.file(urls, path);
        } catch (e) {
            show(e.message);
            return;
        }
        state.path = path;
        rememberRecent(path);
        const name = path.split(/[\\/]/).pop();
        $('file-name').textContent = name;
        $('file-button').title = `${path}\nOpen another file (O)`;
        document.title = `${name} · Analysis`;
        renderFiles();
        if (shell.current === 'files') shell.close();
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
        groupSelect.hidden = state.info.groups.length < 2;
        showDetails();
        show('');
        state.sizing = null;
        loadWeld();
        targetsLoaded = false;
        toReport.picked = new Set();
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
        applyWeld();
        slider.max = scanNumber.max = g.shape[0] - 1;
        $('scan-count').textContent = `of ${g.shape[0]}`;
        state.lateral = Math.min(lateral, g.shape[1] - 1);
        await setScan(Math.min(scan, g.shape[0] - 1));
    }

    const currentGroup = () => state.info.groups.find(g => g.id === state.group);

    // ── the weld overlay: the file's weld, or as edited here (kept per file in this browser) ──
    const weld = { shape: null, shift: 0 };   // shape null: the file's own
    const thickness = () => state.info?.specimen?.thickness || 0;
    const fileWeld = () => (state.info?.weld && Object.keys(state.info.weld).length && state.info.weld_outline?.length ? state.info.weld : null);
    const weldKey = () => `analysisWeld:${state.path}`;
    const weldEdited = () => !!weld.shape || Math.abs(weld.shift) > 1e-9;
    const weldEditor = new WeldEditor($('weld-editor'), {
        unitLength, format, units: () => units,
        onShape: (shape, rebuild) => { weld.shape = shape; saveWeld(); drawWeld(); if (rebuild) showWeldEditor(); },
        onShift: shift => weldShifted(shift, true),
        onReset: () => { weld.shape = null; weld.shift = 0; saveWeld(); applyWeld(); },
        onCreate: () => { weld.shape = defaultWeld(thickness()); saveWeld(); applyWeld(); },
    });

    function loadWeld() {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem(weldKey()) || 'null'); } catch { saved = null; }
        weld.shape = saved?.shape || null;
        weld.shift = Number.isFinite(saved?.shift) ? saved.shift : 0;
    }
    function saveWeld() {
        try {
            if (weldEdited()) localStorage.setItem(weldKey(), JSON.stringify({ shape: weld.shape, shift: weld.shift }));
            else localStorage.removeItem(weldKey());
        } catch { /* not kept */ }
    }

    /** A usual single-V butt weld for a file whose setup has none: 1.6 mm gap and land, 37.5 deg to the surface. */
    function defaultWeld(t) {
        const gap = 0.0008, land = Math.min(0.0016, t / 4), face = t - land;
        const top = gap + face * Math.tan(37.5 * Math.PI / 180);
        return { bevelShape: 'V', offset: gap, land: { height: land }, root: { angle: 0, height: 0 }, hotPass: { angle: 0, height: 0 },
                 fills: [{ angle: 37.5, height: face }], upperCap: { width: 2 * top + 0.003, height: 0.0015 },
                 lowerCap: { width: 2 * gap + 0.003, height: 0.001 } };
    }

    /** The overlay and the Geometry panel for this group (angle-beam groups only). */
    function applyWeld() {
        const g = state.info ? currentGroup() : null;
        const beams = g?.layout === 'beams';
        const shape = beams ? weld.shape || fileWeld() : null;
        $('weld-toggle').hidden = !shape;
        sscan.setWeldShift(weld.shift);
        if (!shape) {
            sscan.setWeld(null);
            weldEditor.show({ message: !state.info ? 'Open a weld scan to see its weld.' : !beams ? 'Weld overlays are for angle-beam weld scans.'
                              : thickness() ? "This file's setup has no weld geometry." : "This file's setup has no weld or part thickness.",
                              canCreate: beams && thickness() > 0 });
            return;
        }
        showWeldEditor();
        drawWeld();
    }
    function showWeldEditor() {
        weldEditor.show({ shape: weld.shape || fileWeld(), shift: weld.shift, edited: weldEdited(), thickness: thickness() });
    }

    let weldRequest = 0;
    async function drawWeld() {
        if (!weld.shape) { sscan.setWeld(state.info.weld_outline, $('show-weld').checked); return; }
        const mine = ++weldRequest;
        let data;
        try {
            data = await send(urls.weldOutline, 'POST', { weld: weld.shape, thickness: thickness() });
        } catch (e) {
            show(e.message);
            return;
        }
        if (mine === weldRequest) sscan.setWeld(data.lines, $('show-weld').checked);
    }

    /** The centre line moved (typed, nudged, or Alt+dragged on the S-scan; `done` when it settles). */
    function weldShifted(shift, done) {
        const wasEdited = weldEdited();
        weld.shift = shift;
        sscan.setWeldShift(shift);
        weldEditor.setShift(shift);
        $('sscan-readout').textContent = `Weld centre line ${format(shift)}`;
        if (!done) return;
        saveWeld();
        if (wasEdited !== weldEdited()) showWeldEditor();   // the "edited" note and the reset button
    }

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
        const saved = (state.indications || []).filter(i => i.group === state.group)
            .map(i => ({ x: scanPosition(i.scan), y: lineY(i.lateral), colour: '#f472b6', label: `#${i.number}` }));
        cview.setCursors({ x: scanLines, y: [{ value: lineY(state.lateral), colour: CURSOR }, ...index],
                           box: z ? z.box : null, marks: [...(z?.mark ? [z.mark] : []), ...saved] });
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
        const letters = state.gates.map(x => letterOf(x.name));   // the gates as edited (added ones too)
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
        for (const [label, help] of [['', ''], [`Start (${units})`, 'Sound path from the pulse, or after the sync gate\'s crossing'],
            [`Width (${units})`, 'Sound path'], ['Thr %', 'Threshold, % of full screen'], ['Sync', 'What the gate starts from']]) {
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
        renderAddGates();
    }

    /** Buttons to add the gates a file doesn't have (I, A, B), set up the usual way. */
    function renderAddGates() {
        const box = $('add-gates');
        const have = new Set(state.gates.map(x => letterOf(x.name)));
        const buttons = ['I', 'A', 'B'].filter(L => !have.has(L)).map(L => {
            const b = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-sm btn-secondary',
                                                                       innerHTML: `<i class="bi bi-plus-lg"></i> Gate ${L}`,
                                                                       title: `Add gate ${L}` });
            b.addEventListener('click', () => addGate(L));
            return b;
        });
        box.replaceChildren(...buttons);
        box.hidden = !buttons.length;
    }

    function addGate(letter) {
        const g = currentGroup();
        const span = g.axes[2].resolution * g.shape[2];
        const start = g.beams[0]?.ultrasound_offset || 0;
        const id = Math.max(-1, ...state.gates.map(x => x.id)) + 1;
        const byLetter = L => state.gates.find(x => letterOf(x.name) === L);
        const gate = { id, name: `Gate ${letter}`, threshold: letter === 'I' ? 35 : 20, trigger: 'Crossing', sync_gate: null,
                       start: start + span * 0.25, length: span * 0.5 };
        if (letter === 'B' && byLetter('A')) Object.assign(gate, { sync_gate: byLetter('A').id, start: span * 0.02, length: span * 0.4 });
        if (letter === 'A' && byLetter('I')) Object.assign(gate, { sync_gate: byLetter('I').id, start: span * 0.02, length: span * 0.4 });
        state.gates.push(gate);
        gatesChanged();
        fillKinds();
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
        fillKinds();
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
            ? [['scan:current', 'Length (scan)'], ['index:current', 'Width (index)']]
            : [['scan:all', 'All beams'], ['scan:current', 'This beam']];
        $('size-over').replaceChildren(...options.map(([v, t]) => new Option(t, v)));
    }

    /** Starts the whole-file build (whatever the layout) and waits for it; true when it's done. */
    async function waitForBuild() {
        for (let i = 0; i < 600; i++) {
            let job;
            try { job = await NdeClient.projections(urls, projectionParams()); } catch { return false; }
            if (job.state === 'done') return true;
            if (job.state === 'error') return false;
            $('size-note').textContent = `Reading the whole file… ${Math.round((job.progress || 0) * 100)}%`;
            await new Promise(r => setTimeout(r, 400));
        }
        return false;
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
        if (response.status === 409) {   // the whole-file data isn't built (e.g. the A-S layout): build it, then size
            note.textContent = 'Reading the whole file first…';
            if (await waitForBuild()) return sizeNow();
            note.textContent = "Couldn't read the whole file.";
            return;
        }
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
        if (shell.current === 'report') renderSendIndications();
        linkCursors();
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
        shell.open('indications');
        loadIndications();
    }

    function renderIndications() {
        const list = state.indications || [];
        $('indication-count').textContent = list.length;
        $('indication-count').hidden = !list.length;
        const box = $('indication-rows');
        if (!list.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), { className: 'analysis-note',
                textContent: 'No indications yet. Size the indication, then Add indication (N) to keep its readings.' }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'analysis-indication-table';
        const head = table.createTHead().insertRow();
        for (const h of ['#', 'Scan', isRaster() ? 'Index' : 'Angle', 'A%', 'Depth', 'Length', '']) {
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
            const remove = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-sm btn-secondary',
                                                                           title: 'Delete this indication', innerHTML: '<i class="bi bi-x-lg"></i>' });
            remove.addEventListener('click', async e => {
                e.stopPropagation();
                try { await send(indicationUrl(item.id), 'DELETE'); } catch (err) { show(err.message); return; }
                loadIndications();
            });
            tr.insertCell().append(remove);
            tr.addEventListener('click', () => goTo(item));
            // The comment on its own line under the row
            const note = body.insertRow();
            note.className = `analysis-indication-note${tr.className ? ' is-current' : ''}`;
            const cell = note.insertCell();
            cell.colSpan = 7;
            cell.append(comment);
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
    $('quick-indication').addEventListener('click', addIndication);

    /** The next (step 1) or previous (-1) saved indication along the scan from here. */
    function stepIndication(step) {
        const list = [...(state.indications || [])].sort((a, b) => a.group - b.group || a.scan - b.scan || a.lateral - b.lateral);
        if (!list.length) return;
        const here = list.findIndex(i => i.group === state.group && i.scan === state.scan && i.lateral === state.lateral);
        let at;
        if (here >= 0) at = (here + step + list.length) % list.length;
        else if (step > 0) at = Math.max(0, list.findIndex(i => i.group > state.group || (i.group === state.group && i.scan > state.scan)));
        else {
            const before = list.filter(i => i.group < state.group || (i.group === state.group && i.scan < state.scan));
            at = before.length ? list.indexOf(before[before.length - 1]) : list.length - 1;
        }
        goTo(list[at]);
    }

    // ── send indications to a report ──
    const toReport = { reports: [], report: null, picked: new Set(), preview: null, timer: null };
    let targetsLoaded = false;

    async function loadReportTargets() {
        try {
            const data = await NdeClient.readings({ readings: urls.reportTargets }, { path: state.path || '' });
            toReport.reports = data.reports;
        } catch (e) {
            toReport.reports = [];
            $('report-list').replaceChildren(note(e.message));
            return;
        }
        targetsLoaded = true;
        if (toReport.report && !toReport.reports.some(r => r.id === toReport.report)) toReport.report = null;
        renderReportTargets();
    }
    const note = text => Object.assign(document.createElement('p'), { className: 'analysis-note', textContent: text });

    function renderReportTargets() {
        const words = $('report-filter').value.toLowerCase().split(/\s+/).filter(Boolean);
        const list = toReport.reports.filter(r => words.every(w => `${r.name} ${r.type} ${r.client}`.toLowerCase().includes(w)));
        if (!list.length) {
            $('report-list').replaceChildren(note(toReport.reports.length ? 'No reports match.' : 'No draft reports. Start one under Reports › New report.'));
            return;
        }
        $('report-list').replaceChildren(...list.map(r => {
            const b = Object.assign(document.createElement('button'), { type: 'button', className: 'analysis-pick' });
            b.classList.toggle('is-current', r.id === toReport.report);
            b.title = `${r.name} · ${r.type}${r.client ? ' · ' + r.client : ''}`;
            b.append(Object.assign(document.createElement('span'), { className: 'name', textContent: r.name }));
            if (r.this_job) b.append(Object.assign(document.createElement('span'), { className: 'tag', textContent: 'This job' }));
            b.append(Object.assign(document.createElement('span'), { className: 'meta', textContent: r.type }));
            b.addEventListener('click', () => { toReport.report = r.id; renderReportTargets(); choiceChanged(); });
            return b;
        }));
    }
    $('report-filter').addEventListener('input', renderReportTargets);

    function renderSendIndications() {
        const list = state.indications || [];
        const known = new Set(list.map(i => i.id));
        toReport.picked = new Set([...toReport.picked].filter(id => known.has(id)));
        if (!list.length) {
            $('send-indications').replaceChildren(note('No indications saved for this file yet (N adds one).'));
            schedulePreview();
            return;
        }
        $('send-indications').replaceChildren(...list.map(item => {
            const label = Object.assign(document.createElement('label'), { className: 'analysis-pick' });
            const box = Object.assign(document.createElement('input'), { type: 'checkbox', checked: toReport.picked.has(item.id) });
            box.addEventListener('change', () => { if (box.checked) toReport.picked.add(item.id); else toReport.picked.delete(item.id); choiceChanged(); });
            const r = item.readings || {};
            const where = isRaster() ? format(item.index_position, true) : (item.angle === null ? '' : `${item.angle}°`);
            label.append(box, Object.assign(document.createElement('span'), { className: 'name',
                textContent: `#${item.number} · ${format(item.scan_position, true)}${where ? ' · ' + where : ''}${item.comment ? ' · ' + item.comment : ''}` }),
                Object.assign(document.createElement('span'), { className: 'meta', textContent: r['A%'] === undefined ? '' : `${r['A%'].toFixed(1)} %` }));
            return label;
        }));
        schedulePreview();
    }
    $('send-all').addEventListener('click', () => {
        const all = (state.indications || []).map(i => i.id);
        toReport.picked = toReport.picked.size === all.length ? new Set() : new Set(all);
        renderSendIndications();
        choiceChanged();
    });
    $('open-send').addEventListener('click', () => {
        if (!toReport.picked.size) toReport.picked = new Set((state.indications || []).map(i => i.id));
        shell.open('report');
    });

    const pickedIndications = () => (state.indications || []).filter(i => toReport.picked.has(i.id));
    /** The rows again for a changed choice (the last send's message goes: it was about other rows). */
    function choiceChanged() {
        $('send-result').textContent = '';
        schedulePreview();
    }
    function schedulePreview() {
        clearTimeout(toReport.timer);
        toReport.timer = setTimeout(loadPreview, 120);
    }

    async function loadPreview() {
        const box = $('send-rows');
        const items = pickedIndications();
        toReport.preview = null;
        updateSendButton();
        if (!toReport.report || !items.length) {
            box.replaceChildren(note(!toReport.report ? 'Pick a report to see the rows.' : 'Pick the indications to send.'));
            return;
        }
        let data;
        try {
            data = await send(urls.reportPreview, 'POST', { report: toReport.report, indications: items.map(i => i.id), units });
        } catch (e) {
            box.replaceChildren(note(e.message));
            return;
        }
        toReport.preview = { ...data, ids: items.map(i => i.id) };
        box.replaceChildren(...data.rows.map((row, r) => {
            const item = items[r];
            const card = Object.assign(document.createElement('div'), { className: 'analysis-send-row' });
            const head = document.createElement('header');
            head.textContent = `Indication #${item.number}`;
            const cells = Object.assign(document.createElement('div'), { className: 'analysis-send-cells' });
            let blank = 0;
            data.columns.forEach((heading, c) => {
                const id = `send-${r}-${c}`;
                const label = Object.assign(document.createElement('label'), { htmlFor: id, textContent: heading });
                label.title = data.fields[c] ? `${heading}: ${data.field_names[data.fields[c]]}` : `${heading}: nothing from the analysis, fill it in if you like`;
                const input = Object.assign(document.createElement('input'), { type: 'text', id, value: row[c], className: 'form-control mono' });
                input.addEventListener('input', () => { toReport.preview.rows[r][c] = input.value; });
                if (!row[c]) { label.classList.add('is-blank'); input.classList.add('is-blank'); blank++; }
                cells.append(label, input);
            });
            card.append(head, cells);
            if (blank) {
                const more = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-link analysis-send-more',
                                                                             textContent: `+ ${blank} blank column${blank > 1 ? 's' : ''}` });
                more.addEventListener('click', () => {
                    const on = card.classList.toggle('show-all');
                    more.textContent = on ? 'Hide the blank columns' : `+ ${blank} blank column${blank > 1 ? 's' : ''}`;
                });
                card.append(more);
            }
            return card;
        }));
        if (data.report.issued) box.prepend(note('This report is issued - reopen it before adding indications.'));
        updateSendButton();
    }

    function updateSendButton() {
        const p = toReport.preview;
        const button = $('send-now');
        button.disabled = !p || p.report.issued;
        button.innerHTML = `<i class="bi bi-send"></i> ${p ? `Add ${p.rows.length} row${p.rows.length > 1 ? 's' : ''} to ${p.report.name}` : 'Add to report'}`;
    }

    const wait = ms => new Promise(r => setTimeout(r, ms));
    /** Each indication's picture: the views at it (as laid out now), back where we were afterwards. */
    async function picturesOf(items) {
        const here = { group: state.group, scan: state.scan, lateral: state.lateral, cursors: { ...state.cursors }, sizing: state.sizing };
        const out = [];
        for (const [n, item] of items.entries()) {
            $('send-result').textContent = `Taking the pictures… ${n + 1} of ${items.length}`;
            await goTo(item);
            await wait(150);
            await loadReadings();
            await wait(350);   // the B-scan and the overlays follow the cursor
            out.push(composeImage().toDataURL('image/png'));
        }
        if (here.group !== state.group) await setGroup(here.group, here.scan, here.lateral);
        state.sizing = here.sizing;
        setCursors(here.cursors);
        await setScan(here.scan);
        setLateral(here.lateral, true);
        return out;
    }

    $('send-now').addEventListener('click', async () => {
        const p = toReport.preview;
        if (!p) return;
        const button = $('send-now'), result = $('send-result');
        button.disabled = true;
        const items = p.ids.map(id => (state.indications || []).find(i => i.id === id)).filter(Boolean);
        let pictures = null;
        try {
            if ($('send-pictures').checked && state.info) pictures = await picturesOf(items);
            result.textContent = 'Adding…';
            const done = await send(urls.reportSend, 'POST', { report: p.report.id, indications: p.ids, columns: p.columns,
                                                              rows: p.rows, pictures });
            result.replaceChildren(`Added ${done.added} row${done.added > 1 ? 's' : ''}. `,
                Object.assign(document.createElement('a'), { href: done.edit_url, target: '_blank', rel: 'noopener', textContent: 'Open the report' }));
            toReport.picked = new Set();
            toReport.preview = null;
            renderSendIndications();
            updateSendButton();
        } catch (e) {
            result.textContent = e.message;
            button.disabled = false;
        }
    });

    function reportPanelOpened(name) {
        if (name !== 'report') return;
        if (!targetsLoaded) loadReportTargets();
        renderSendIndications();
    }
    shell.onChange(reportPanelOpened);
    reportPanelOpened(shell.current);   // still open from last time

    // ── picture of the views ──
    /** The visible views as laid out on screen, their titles, and the readings, on one canvas. */
    function composeImage() {
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
            // The title, what the view shows (e.g. the C-scan's kind) and its note
            const label = [...head.querySelectorAll(':scope > span, :scope > select')]
                .map(el => (el.tagName === 'SELECT' ? el.selectedOptions[0]?.text || '' : el.textContent).trim()).filter(Boolean).join('  ');
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
        return out;
    }

    /** The picture of the views, saved as a PNG. */
    function saveImage() {
        if (!state.info) return;
        composeImage().toBlob(blob => {
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

    const toggleHelp = force => { const panel = $('help-panel'); panel.hidden = force === undefined ? !panel.hidden : !force; };
    $('show-help').addEventListener('click', () => toggleHelp());
    $('close-help').addEventListener('click', () => toggleHelp(false));
    function fitAll() {
        sscan.view = null; sscan.draw();
        cview.view = null; cview.draw();
        bview.view = null; bview.draw();
        ascan.resetZoom();
    }

    // ── controls ──
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
            showDetails(); renderGates(); renderReadings(); setLateral(state.lateral, true); if (currentGroup()?.layout === 'beams' && (weld.shape || fileWeld())) showWeldEditor();
            $('scan-position').textContent = `= ${format(scanPosition(state.scan))}`;
            cview.drawOverlay(); bview.drawOverlay();
            if (state.cscan && state.cscan.mode !== 'amplitude') loadCscan(projectionRequest);
            renderIndications();
            if (state.path) $('export-indications').href = `${urls.indicationsCsv}?${new URLSearchParams({ path: state.path, units })}`;
        }
    });
    axisSelect.addEventListener('change', () => ascan.setAxis(axisSelect.value));
    $('sscan-fit').addEventListener('click', () => { sscan.view = null; sscan.draw(); });
    $('true-geometry').addEventListener('change', e => sscan.setTrueGeometry(e.target.checked));
    $('show-weld').addEventListener('change', e => { sscan.showWeld = e.target.checked; sscan.drawOverlay(); });

    document.addEventListener('keydown', e => {
        if (e.target.closest?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
        const always = {   // with or without a file open
            o: () => { shell.open('files'); fileFilter.focus(); }, O: () => { shell.open('files'); fileFilter.focus(); },
            r: shell.toggleReadings, R: shell.toggleReadings, '?': () => toggleHelp(),
            Escape: () => { if (!$('help-panel').hidden) toggleHelp(false); else shell.close(); },
        };
        if (always[e.key]) { e.preventDefault(); always[e.key](); return; }
        if (!state.info) return;
        const big = e.shiftKey ? 10 : 1;
        const actions = {
            ArrowLeft: () => setScan(state.scan - big), ArrowRight: () => setScan(state.scan + big),
            PageUp: () => setScan(state.scan - 10), PageDown: () => setScan(state.scan + 10),
            ArrowUp: () => setLateral(state.lateral - 1), ArrowDown: () => setLateral(state.lateral + 1),
            '+': () => setGain(state.gain + 1), '=': () => setGain(state.gain + 1), '-': () => setGain(state.gain - 1),
            l: sizeNow, L: sizeNow, n: addIndication, N: addIndication, g: nextGroup, G: nextGroup, p: saveImage, P: saveImage, f: fitAll, F: fitAll, ']': () => stepIndication(1), '[': () => stepIndication(-1),
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
    grid.classList.add('is-empty');
    applyWeld();
    page.views = { sscan, ascan, cview, bview };   // for checking the page in a test browser
    loadFiles().catch(e => show(e.message));
})();
