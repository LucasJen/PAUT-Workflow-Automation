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
                   readings: page.dataset.readingsUrl, frameGates: page.dataset.frameGatesUrl, projections: page.dataset.projectionsUrl,
                   cscan: page.dataset.cscanUrl, bscan: page.dataset.bscanUrl, size: page.dataset.sizeUrl,
                   indications: page.dataset.indicationsUrl, indicationsCsv: page.dataset.indicationsCsvUrl,
                   indication: page.dataset.indicationUrl, reportTargets: page.dataset.reportTargetsUrl,
                   reportPreview: page.dataset.reportPreviewUrl, weldOutline: page.dataset.weldOutlineUrl, reportSend: page.dataset.reportSendUrl,
                   detect: page.dataset.detectUrl, clearIndications: page.dataset.clearIndicationsUrl, resize: page.dataset.resizeUrl,
                   forgetIndications: page.dataset.forgetIndicationsUrl };
    const $ = id => document.getElementById(id);
    const fileList = $('file-list'), fileFilter = $('file-filter'), groupSelect = $('group-select');
    const shell = window.AnalysisShell;
    const scanNumber = $('scan-number'), gainInput = $('gain');
    const unitsSelect = $('units'), axisSelect = $('axis'), refInput = $('ref-level');
    const status = $('analysis-status');
    const grid = $('analysis-grid'), layoutSelect = $('layout'), kindSelect = $('cscan-kind');
    const panels = AnalysisLayout(grid, layoutSelect);
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
                    cscan: null, cscanGain: 0, cscanRanges: {},
                    // The soft gain the whole-file views are built at: reviewing an indication shows it at its own
                    // 80 % gain without building them again (the views' shaders take the difference)
                    buildGain: 0, reviewing: null, filter: 'all' };
    const params = new URLSearchParams(location.search);
    let units = localStorage.getItem('analysisUnits') || 'in';
    unitsSelect.value = units;

    const unitLength = () => (units === 'mm' ? 0.001 : 0.0254);
    /** A length in the page's units: '0.402 in'; short=true an axis tick ('0.40'); short='value' a bare reading ('0.402'). */
    const format = (m, short = false) => {
        if (m === null || m === undefined || Number.isNaN(m)) return '-';
        const v = m / unitLength();
        const places = (units === 'mm' ? 2 : 3) - (short === true ? 1 : 0);
        return `${v.toFixed(places)}${short ? '' : units === 'mm' ? ' mm' : ' in'}`;
    };
    const show = text => { status.textContent = text || ''; status.hidden = !text; };

    const sscan = new SScanView($('sscan-stage'), {
        format, unitLength,
        onCursor: lateral => setLateral(lateral),
        onCursors: partial => setCursors(partial),
        onWeldShift: (shift, done) => weldShifted(shift, done),
        onGateDragStart: letter => { gateSnapshot = structuredClone(gateByLetter(letter)); gateDragStarted(); },
        onGateDrag: (letter, part, delta) => dragGateOnSscan(letter, part, delta),
        onGateDragEnd: () => gateDragEnded(),
        onSelect: select, onWheel: e => wheelSelected(e, sscan),
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
        onGateDragStart: letter => {
            gateSnapshot = { ...gateByLetter(letter) };
            const shown = state.gateResults?.[letter];   // a floating gate's bar is at its height here, not its threshold
            gateSnapshot.drawn = shown?.band ? (shown.threshold ?? shown.band[0]) : gateSnapshot.threshold;
            gateDragStarted();
        },
        onGateDrag: (letter, drag) => dragGateOnAscan(letter, drag),
        onSelect: select, onWheel: e => wheelSelected(e, ascan),
        onGateDragEnd: () => gateDragEnded(),
    });

    /** A gate dragged (or wheeled) on the A-scan: part move / start / end by dt (s) since the press; threshold: the bar's new height. */
    function dragGateOnAscan(letter, { part, dt, threshold: dragged }) {
        const gate = gateByLetter(letter);
        if (!gate || !gateSnapshot) return;
        const threshold = dragged === undefined || !isFloating(gate) || !gateSnapshot.drawn ? dragged
            : gateSnapshot.threshold * dragged / gateSnapshot.drawn;   // keep the ratio: move the calibrated height
        const minimum = currentGroup().axes[2].resolution;
        if ((gate.geometry || 'SoundPath') !== 'SoundPath') {
            const dd = dt * halfVelocity() * (currentGroup().rays[state.lateral]?.dz || 1);
            const lo = gateSnapshot.depth_start, hi = gateSnapshot.depth_end, least = minimum * halfVelocity();
            if (part === 'move') {
                gate.depth_start = lo + dd; gate.depth_end = hi + dd;
                if (threshold !== undefined) gate.threshold = Math.round(threshold);
            } else if (part === 'start') {   // the start carries the end with it: the height stays
                gate.depth_start = lo + dd; gate.depth_end = hi + dd;
            } else gate.depth_end = Math.max(hi + dd, lo + least);
            gatesChanged(20);
            previewDraggedGate(letter);
            return;
        }
        if (part === 'move') {
            gate.start = gateSnapshot.start + dt;
            if (threshold !== undefined) gate.threshold = Math.round(threshold);
        } else if (part === 'start') {   // the start carries the end with it: the width stays (the end sets it)
            gate.start = gateSnapshot.start + dt;
        } else {
            gate.length = Math.max(minimum, gateSnapshot.length + dt);
        }
        gatesChanged(20);
        previewDraggedGate(letter);
    }

    /**
     * While a gate is dragged the A-scan draws it from its settings at once (the server's last readings
     * moved by what the drag changed); the readings, the synced gates' windows and the C- / B-scans follow
     * when it's let go - so the drag doesn't wait on the server.
     */
    let dragBase = null;
    function gateDragStarted() {
        state.draggingGate = true;
        dragBase = state.gateResults ? structuredClone(state.gateResults) : null;
    }
    function gateDragEnded() {
        state.draggingGate = false;
        gateSnapshot = null;
        dragBase = null;
        scheduleReadings(0);
        loadFrameGates();
        scheduleProjections(300);
    }
    /** The A-scan's gates with the dragged one where its settings now put it. */
    function previewDraggedGate(letter) {
        const base = dragBase?.[letter], gate = gateByLetter(letter), s = gateSnapshot;
        if (!base || !gate || !s || base.start === null || base.start === undefined) return;
        const g = currentGroup(), r = g.rays[state.lateral], hv = halfVelocity() || 1;
        let d0, d1;
        if ((gate.geometry || 'SoundPath') === 'SoundPath') {
            d0 = gate.start - s.start;
            d1 = gate.start + gate.length - s.start - s.length;
        } else {   // depths to this beam's times
            const per = 1 / (hv * (Math.abs(r?.dz) || 1));
            d0 = (gate.depth_start - s.depth_start) * per;
            d1 = (gate.depth_end - s.depth_end) * per;
        }
        const scale = s.threshold ? gate.threshold / s.threshold : 1;
        const moved = { ...base, start: base.start + d0, end: base.end + d1,
                        threshold: base.threshold === null || base.threshold === undefined ? base.threshold
                            : (base.band ? base.threshold * scale : gate.threshold),
                        band: base.band ? base.band.map(b => b * scale) : base.band };
        ascan.set({ gates: { ...(state.gateResults || dragBase), [letter]: moved } });
    }

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
        onBox: (box, done) => {   // contour sizing: a box drawn with Alt+drag
            state.contour = { ...box };
            linkCursors();
            if (done) sizeInBox();
        },
        onDraw: () => drawEcho(),
        onWheel: e => wheelSelected(e, cview),
        formatX: x => format(x, true), formatY: y => (isRaster() ? format(y, true) : lineText(y)),
        formatRange: v => format(v, true),
        xUnit: unitLength, yUnit: () => (isRaster() ? unitLength() : 1),
        onPick: ({ x, y, event }) => {
            const [column, row, inside] = cscanCell(x, y);
            if (event.ctrlKey || event.shiftKey) {   // reference / measure: scan (and index on a raster)
                const which = event.shiftKey ? 'meas' : 'ref';
                setCursors({ [`s_${which}`]: x, ...(isRaster() ? { [`i_${which}`]: y } : {}) });
                select({ kind: 'cursor', key: `s_${which}` });
                return;
            }
            if (!inside) return;
            select({ kind: 'scan' });
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
        onWheel: e => wheelSelected(e, bview),
        onPick: ({ x, y, event }) => {
            const [column] = cscanCell(x, 0);
            const inside = column >= 0 && column < currentGroup().shape[0];
            if (event.ctrlKey || event.shiftKey) {   // reference / measure: scan and depth
                const which = event.shiftKey ? 'meas' : 'ref';
                setCursors({ [`s_${which}`]: x, [`u_${which}`]: y });
                select({ kind: 'cursor', key: `s_${which}` });
                return;
            }
            select({ kind: 'scan' });
            if (inside && column !== state.scan) setScan(column);
        },
        onHover: (x, y) => { $('bscan-readout').textContent = x === null ? '' : `Scan ${format(x)} · depth ${format(y)}`; },
    });
    // Zoom bars under and beside each view: each axis zoomed and moved on its own (the wheel zooms both)
    for (const [view, name] of [[sscan, 'sscan'], [ascan, 'ascan'], [cview, 'cscan'], [bview, 'bscan']]) {
        ZoomBars.attach(view, $(`${name}-zoom-x`), $(`${name}-zoom-y`));
    }
    panels.onTurn = () => { for (const view of [sscan, ascan, cview, bview]) view.draw(); };   // the text upright again

    // Linked zooms (Display panel): a view zoomed or panned along a linked axis takes the others with it,
    // in world units - scan (C- and B-scan across), depth (B- and S-scan down, the A-scan across when it
    // shows true depth), index (S-scan across, a raster's C-scan down). The S-scan's axes are as unrotated
    // here; screenAxis turns them when it's rotated (depth across, index down)
    const ZOOM_LINKS = {
        scan: [[cview, 'x'], [bview, 'x']],
        depth: [[bview, 'y'], [sscan, 'y'], [ascan, 'x']],
        index: [[sscan, 'x'], [cview, 'y']],
    };
    const zoomLinks = { scan: false, depth: false, index: false };
    try { Object.assign(zoomLinks, JSON.parse(localStorage.getItem('analysisZoomLinks') || '{}')); } catch { /* none */ }
    /** Whether `view` can share `link`: the A-scan's depth only in true depth, the C-scan's index only on a raster. */
    const linkable = (link, view) => !(link === 'depth' && view === ascan && ascan.axis !== 'depth')
        && !(link === 'index' && view === cview && !isRaster());
    const screenAxis = (view, axis) => (view === sscan && sscan.rotated ? (axis === 'x' ? 'y' : 'x') : axis);
    let linking = false;
    function zoomFollow(view, only = null) {
        if (linking) return;   // a view moved by a link doesn't pass it on again
        linking = true;
        try {
            for (const [link, members] of Object.entries(ZOOM_LINKS)) {
                if (!zoomLinks[link] || (only && link !== only)) continue;
                const mine = members.find(([v]) => v === view);
                if (!mine || !linkable(link, view)) continue;
                const range = view.axisRange(screenAxis(view, mine[1]));
                if (!range) continue;
                for (const [other, axis] of members) {
                    const on = screenAxis(other, axis);
                    if (other !== view && linkable(link, other) && other.axisRange(on)) other.setAxisRange(on, range.shown);
                }
            }
        } finally { linking = false; }
    }
    for (const view of [sscan, ascan, cview, bview]) view.options.onViewChange = zoomFollow;

    for (const link of Object.keys(ZOOM_LINKS)) {
        const box = $(`link-${link}`);
        box.checked = zoomLinks[link];
        box.addEventListener('change', () => {
            zoomLinks[link] = box.checked;
            try { localStorage.setItem('analysisZoomLinks', JSON.stringify(zoomLinks)); } catch { /* not kept */ }
            const first = ZOOM_LINKS[link].find(([v, axis]) => linkable(link, v) && v.axisRange(screenAxis(v, axis)));
            if (box.checked && first) zoomFollow(first[0], link);   // line them up now
        });
    }

    // ── the selected cursor / gate: the wheel moves it a step a notch (Shift: 10), Ctrl+wheel zooms ──
    /** {kind: 'cursor', key: 'u_ref' ...} | {kind: 'scan'} | {kind: 'lateral'} | {kind: 'gate', view, letter, part, line} | null */
    function select(selected) {
        state.selected = selected;
        sscan.setSelected(selected);
        ascan.setSelected(selected);
        linkCursors();
        renderSelection();
    }
    const selectedIs = (kind, key) => state.selected?.kind === kind && (key === undefined || state.selected.key === key);

    /** The selection and where it is, in the top bar - an editable value: type a new one (Enter) or scroll
     *  over it. A cursor's value, the beam (angle / VPA / index) or scan line, the gate part being moved (its
     *  start; its width when the end is picked; a true-depth gate's top or height; a box's side). */
    const CURSOR_NAMES = { u: 'U', s: 'S', i: 'I' };
    let selectionApply = null;   // sets the selection to a typed value (page units)
    function renderSelection() {
        const sel = state.selected, out = $('selection-readout'), input = $('selection-value');
        const g = currentGroup(), L = unitLength();
        let colour = null, name = '', value = null, unit = units, note = '', apply = null;
        if (sel && g && state.info) {
            if (sel.kind === 'cursor') {
                const v = state.cursors[sel.key];
                colour = sel.key.endsWith('ref') ? '#f87171' : '#4ade80';
                name = `${CURSOR_NAMES[sel.key[0]]}(${sel.key.endsWith('ref') ? 'r' : 'm'})`;
                value = has(v) ? format(v, 'value') : '';
                apply = x => setCursors({ [sel.key]: x * L });
            } else if (sel.kind === 'scan') {
                colour = CURSOR; name = 'Scan';
                value = format(scanPosition(state.scan), 'value');
                note = `line ${state.scan + 1}`;
                apply = x => setScan(Math.round((x * L - scanAxis().offset) / scanAxis().resolution));
            } else if (sel.kind === 'lateral') {
                colour = CURSOR;
                const mode = beamMode(), beam = g.beams[state.lateral];
                name = mode === 'index' ? 'Index' : mode === 'vpa' ? 'VPA' : 'Beam';
                value = mode === 'angle' ? String(beam?.refracted_angle ?? '') : mode === 'vpa' ? String(state.lateral + 1) : format(lineY(state.lateral), 'value');
                unit = mode === 'angle' ? '°' : mode === 'vpa' ? '' : units;
                apply = x => goToBeam(String(x));
            } else if (sel.kind === 'gate') {
                const gate = gateByLetter(sel.letter);
                if (gate) {
                    colour = GATE_COLOURS[sel.letter] || '#a78bfa';
                    const geometry = gate.geometry || 'SoundPath', part = sel.part;
                    const hv = () => halfVelocity() || 1, least = currentGroup().axes[2].resolution;
                    let what;
                    if (geometry === 'SoundPath') {
                        what = part === 'end' ? 'width' : 'start';
                        value = gateLength(part === 'end' ? gate.length : gate.start);
                        apply = part === 'end' ? x => { gate.length = Math.max(least, x * L / hv()); }
                            : x => { gate.start = x * L / hv(); };   // the end moves with it
                    } else if (part === 'end') {
                        what = 'height'; value = format(gate.depth_end - gate.depth_start, 'value');
                        apply = x => { if (x > 0) gate.depth_end = gate.depth_start + x * L; };
                    } else if (part === 'd1') {
                        what = 'bottom'; value = format(gate.depth_end, 'value');
                        apply = x => { gate.depth_end = x * L; };
                    } else if (part === 'i0' || part === 'i1') {
                        const key = part === 'i0' ? 'index_start' : 'index_end';
                        what = part === 'i0' ? 'index from' : 'index to'; value = format(gate[key], 'value');
                        apply = x => { gate[key] = x * L; };
                    } else {
                        what = 'top'; value = format(gate.depth_start, 'value');
                        apply = x => {   // a true-depth gate's top carries its bottom; a box's top is its own side
                            const h = gate.depth_end - gate.depth_start;
                            gate.depth_start = x * L;
                            if (geometry !== 'Box' || part !== 'd0') gate.depth_end = gate.depth_start + h;
                        };
                    }
                    name = `Gate ${sel.letter} ${what}`;
                    if (part === 'move' && sel.view === 'ascan') note = `${Math.round(gate.threshold * 10) / 10} %`;   // up / down there is the threshold
                    const set = apply;
                    apply = x => { set(x); gatesChanged(); renderGates(); };
                }
            }
        }
        out.hidden = !colour;
        selectionApply = colour ? apply : null;
        if (!colour) return;
        out.style.setProperty('--sel-colour', colour);
        $('selection-name').textContent = name;
        $('selection-unit').textContent = unit;
        $('selection-note').textContent = note;
        $('selection-note').hidden = !note;
        if (document.activeElement !== input) input.value = value ?? '';
    }
    /** A view's wheel: moves the selection and returns true, or false (nothing selected: the view zooms). */
    function wheelSelected(e, view) {
        if (!state.selected || !state.info) return false;
        const delta = e.deltaY || e.deltaX;   // Shift+wheel comes as deltaX
        if (delta) nudge(Math.sign(delta) * (e.shiftKey ? 10 : 1), view);
        return true;
    }
    /** Data steps a notch moves a cursor or gate: about 1/200 of what `view` shows along `axis`, at least one. */
    function perNotch(view, axis, step) {
        const r = view?.axisRange?.(axis);
        return r && step ? Math.max(1, Math.round(Math.abs(r.shown[1] - r.shown[0]) / 200 / step)) : 1;
    }
    /** One step of a cursor along its axis: a sample's depth (u), a scan line (s), an index step (i). */
    function cursorStep(axis) {
        const g = currentGroup(), r = g.rays[state.lateral];
        if (axis === 's') return Math.abs(g.axes[0].resolution);
        if (axis === 'i') return isRaster() ? Math.abs(g.axes[1].resolution) : r.sp_step * (Math.abs(r.dv) || 1);
        return r.sp_step * (Math.abs(r.dz) || 1);
    }
    /** Move the selection `steps` notches; `view` is the one wheeled (its zoom sets a cursor's or gate's step). */
    function nudge(steps, view) {
        const sel = state.selected, g = currentGroup();
        if (!g) return;
        if (sel.kind === 'scan') { setScan(state.scan + steps); return; }
        if (sel.kind === 'lateral') { setLateral(state.lateral + steps); return; }
        if (sel.kind === 'cursor') {
            const value = state.cursors[sel.key], axis = sel.key[0], step = cursorStep(axis);
            // The view's axis it runs along: the A-scan's is across; depth is down; scan across; index across (C-scan: down)
            const along = view === ascan ? 'x' : axis === 'u' ? 'y' : axis === 's' ? 'x' : view === cview ? 'y' : 'x';
            if (has(value)) setCursors({ [sel.key]: value + steps * perNotch(view, screenAxis(view, along), step) * step });
            return;
        }
        if (sel.kind !== 'gate' || !gateByLetter(sel.letter)) return;
        gateSnapshot = structuredClone(gateByLetter(sel.letter));   // the drags work from a snapshot
        const ray = g.rays[sel.line ?? state.lateral];
        if (sel.view === 'sscan') {
            const r = ray, sp = steps * perNotch(sscan, screenAxis(sscan, 'y'), r.sp_step * (Math.abs(r.dz) || 1)) * r.sp_step;
            dragGateOnSscan(sel.letter, sel.part, { dx: sp, dy: sp * (Math.abs(r.dz) || 1), dsp: sp, line: sel.line });
            loadFrameGates();
        } else {
            const sample = ray.sp_step * (ascan.axis === 'depth' ? Math.abs(ray.dz) || 1 : 1);   // a sample along the A-scan
            dragGateOnAscan(sel.letter, { part: sel.part, dt: steps * perNotch(ascan, 'x', sample) * g.axes[2].resolution });
        }
        gateSnapshot = null;
    }

    // ── per file / group memory: this tab's session only. Every open of a file starts fresh, as if for
    // the first time (its own gates, no cursors or saved indications - see openFile); a refresh of the
    // same file in the same tab carries on. Older versions kept this in localStorage: dropped once here.
    const PER_FILE = ['analysis:', 'analysisWeld:', 'analysisSkew:'];
    try {
        Object.keys(localStorage).filter(k => PER_FILE.some(prefix => k.startsWith(prefix))).forEach(k => localStorage.removeItem(k));
    } catch { /* nothing kept */ }
    /** Forgets what this tab kept for a file (gates, cursors, reference level, weld edits, skew view). */
    function forgetFileState(path) {
        try {
            Object.keys(sessionStorage).filter(k => PER_FILE.some(prefix => k === `${prefix}${path}` || k.startsWith(`${prefix}${path}:`)))
                .forEach(k => sessionStorage.removeItem(k));
        } catch { /* nothing kept */ }
    }
    const memoryKey = () => `analysis:${state.path}:${state.group}`;
    function save() {
        try {
            sessionStorage.setItem(memoryKey(), JSON.stringify({
                gates: state.gatesEdited ? state.gates : null, cursors: state.cursors, refLevel: state.refLevel,
            }));
        } catch { /* storage full or blocked: nothing to keep */ }
    }
    function restore() {
        let saved = null;
        try { saved = JSON.parse(sessionStorage.getItem(memoryKey()) || 'null'); } catch { saved = null; }
        const g = currentGroup();
        state.gates = saved?.gates || fileGates(g);
        state.gatesEdited = !!saved?.gates;
        state.cursors = { ...NO_CURSORS, ...(saved?.cursors || {}) };
        state.refLevel = saved?.refLevel || 80;
        refInput.value = state.refLevel;
    }
    // The file's gates as set up: sound path, or true depth (between two depths on every beam)
    // Where a gate measures from (its position readings): edge - the threshold crossing (/), peak - the first
    // peak after it, max peak - its highest sample (^, as OmniPC)
    const DETECTION_NAMES = { edge: 'edge (threshold crossing)', peak: 'first peak', maxpeak: 'max peak' };
    const detectionMark = letter => ((gateByLetter(letter)?.detection || 'edge') === 'edge' ? '/' : '^');
    const fileGates = g => g.gates.map(x => ({
        id: x.id, name: x.name, start: x.start, length: x.length, threshold: x.threshold, detection: x.detection || 'edge',
        geometry: x.geometry === 'TrueDepth' && x.depth_start !== null && x.depth_end !== null ? 'TrueDepth' : 'SoundPath',
        ...(x.geometry === 'TrueDepth' ? { depth_start: x.depth_start, depth_end: x.depth_end } : {}),
        sync_gate: x.sync_mode === 'GateRelative' ? x.sync_gate : null, trigger: x.trigger || 'Crossing',
    }));
    const letterOf = name => (name || '').trim().split(/\s+/).pop().toUpperCase();
    const gateByLetter = letter => state.gates.find(x => letterOf(x.name) === letter);

    function remember() {
        const q = new URLSearchParams({ path: state.path, group: state.group, scan: state.scan, lateral: state.lateral });
        history.replaceState(null, '', `${location.pathname}?${q}`);
    }

    // ── files and groups ──
    let allFiles = [], openedFiles = [];
    /** The working folders' files and those opened from elsewhere on this PC, listed in the Files panel. */
    async function fetchFiles() {
        const data = await NdeClient.files(urls);
        allFiles = data.files;
        openedFiles = data.opened || [];
        renderFiles();
    }
    async function loadFiles() {
        await fetchFiles();
        const known = new Set([...allFiles, ...openedFiles].map(f => f.path));
        const wanted = params.get('path') || recentFiles().find(p => known.has(p));
        if (wanted && known.has(wanted)) {
            let carryOn = false;
            try { carryOn = sessionStorage.getItem('analysisOpen') === wanted; } catch { /* fresh */ }
            await openFile(wanted, +params.get('group') || 0, +params.get('scan') || 0, +params.get('lateral') || 0, { fresh: !carryOn });
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
        // Long ones keep the working folder and the last two folders: 'Reports › … › Job › Sub'
        const folderOf = f => {
            const parts = [rootName(f), ...(f.folder === '.' ? [] : f.folder.split(/[\\/]/))];
            return (parts.length > 3 ? [parts[0], '…', ...parts.slice(-2)] : parts).join(' › ');
        };
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
        const byPath = new Map([...allFiles, ...openedFiles].map(f => [f.path, f]));
        // Opened from elsewhere on this PC (Browse PC): each can be forgotten; together, a new project
        const opened = openedFiles.filter(f => words.every(w => f.path.toLowerCase().includes(w)));
        if (opened.length) {
            const head = heading('Opened from this PC');
            const make = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-link', textContent: 'New project…',
                                                                         title: 'Make a job folder with these files and start a report from them' });
            make.addEventListener('click', () => filesPanel.newProject(opened.map(f => f.path)));
            head.append(make);
            out.push(head);
            for (const f of opened) {
                const row = item(f, f.folder.split(/[\\/]/).filter(Boolean).pop() || f.folder);
                const forget = Object.assign(document.createElement('span'), { className: 'forget', role: 'button', tabIndex: 0,
                                                                             title: 'Take it off this list', innerHTML: '<i class="bi bi-x"></i>' });
                forget.addEventListener('click', e => { e.stopPropagation(); filesPanel.forget(f.path); });
                row.append(forget);
                out.push(row);
            }
        }
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
                textContent: allFiles.length || openedFiles.length ? 'No files match.' : 'No .nde files in the working folders - Browse PC opens one from anywhere.' }));
        }
        fileList.replaceChildren(...out);
    }
    fileFilter.addEventListener('input', renderFiles);
    fileFilter.addEventListener('keydown', e => {   // Enter opens the first match
        if (e.key !== 'Enter') return;
        const first = fileList.querySelector('.analysis-file-item');
        if (first) first.click();
    });
    const filesPanel = AnalysisFiles({ page, send, openFile: path => openFile(path), refreshFiles: fetchFiles });
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

    /** Opens a file. fresh (every open but a refresh of this tab's file): as if for the first time - what
     *  this tab kept for it is forgotten and its saved indications are deleted. */
    async function openFile(path, group = 0, scan = 0, lateral = 0, { fresh = true } = {}) {
        show('Opening…');
        grid.classList.remove('is-empty');
        try {
            state.info = await NdeClient.file(urls, path);
        } catch (e) {
            show(e.message);
            return;
        }
        let cleared = 0;
        if (fresh) {
            forgetFileState(path);
            try { cleared = (await send(urls.forgetIndications, 'POST', { path })).deleted || 0; } catch (e) { show(e.message); }
        }
        try { sessionStorage.setItem('analysisOpen', path); } catch { /* every load fresh */ }
        $('find-note').textContent = cleared ? `Opened fresh - cleared ${cleared} saved indication${cleared === 1 ? '' : 's'}.` : '';
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
        state.contour = null;
        state.reviewing = null;
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
        // A preset: its layout, with its views' places, turns and sizes
        grid.dataset.layout = panels.usePreset(layoutSelect.value) || layoutSelect.value;
        panels.refresh();
        try { localStorage.setItem(`analysisLayout:${isRaster() ? 'raster' : 'beams'}`, grid.dataset.layout); } catch { /* not kept */ }
        scheduleProjections();
    });

    async function setGroup(id, scan = 0, lateral = 0) {
        state.group = id;
        const g = currentGroup();
        restore();
        applyLayout();
        state.cscan = null;
        state.contour = null;   // a box on the other group's C-scan
        cview.clear('');
        bview.clear('');
        fillKinds();
        fillSizeOver();
        scheduleProjections();
        renderGates();
        sscan.setGeometry(g.rays, g.shape[2], state.info.specimen?.thickness);
        applySkew();
        sscan.setCursors(state.cursors);
        $('true-geometry').checked = sscan.trueGeometry;
        $('groups-toggle').hidden = otherGroups().length === 0;
        applyWeld();
        applyLegs();
        state.lateral = Math.min(lateral, g.shape[1] - 1);
        await setScan(Math.min(scan, g.shape[0] - 1));
    }

    const currentGroup = () => state.info.groups.find(g => g.id === state.group);

    /** The leg lines (T, 2T, ...) on the S-, A- and B-scans at the part's thickness, if it's known. */
    function applyLegs() {
        const on = $('show-legs').checked;
        const t = state.info?.specimen?.thickness || 0;
        sscan.setLegs(on);
        ascan.setLegs(on && t ? t : null);
        bview.setGuides(on && t ? Array.from({ length: 20 }, (_, i) => ({ y: (i + 1) * t, label: i ? `${i + 1}T` : 'T' })) : []);
    }
    try { $('show-legs').checked = localStorage.getItem('analysisLegs') !== '0'; } catch { /* on */ }
    $('show-legs').addEventListener('change', () => {
        try { localStorage.setItem('analysisLegs', $('show-legs').checked ? '1' : '0'); } catch { /* not kept */ }
        applyLegs();
    });
    const toggleLegs = () => { $('show-legs').checked = !$('show-legs').checked; $('show-legs').dispatchEvent(new Event('change')); };

    /** The top bar's scan position: the distance box, its line number on hover. */
    function showScanPosition() {
        const g = currentGroup();
        const position = format(scanPosition(state.scan), 'value');
        if (document.activeElement !== scanNumber) scanNumber.value = position;
        scanNumber.title = `${position} ${units}: scan line ${state.scan + 1} of ${g.shape[0]} (Left / Right a line, Shift for 10, PageUp / PageDown)`;
        $('scan-unit').textContent = units;
    }

    /**
     * The data cursor's beam in the top bar: its refracted angle on a sectorial scan, its VPA (the line,
     * from 1) on a linear one (every beam at one angle), its index position on a raster.
     */
    function beamMode() {
        const g = currentGroup();
        if (!g) return 'angle';
        if (isRaster()) return 'index';
        const angles = new Set(g.beams.map(b => b.refracted_angle));
        return angles.size > 1 ? 'angle' : 'vpa';
    }
    function showBeam() {
        const g = currentGroup(), box = $('beam-number');
        if (!g) return;
        const mode = beamMode();
        $('beam-prefix').hidden = mode !== 'vpa';
        $('beam-unit').hidden = mode === 'vpa';
        $('beam-unit').textContent = mode === 'angle' ? '°' : units;
        if (document.activeElement === box) return;
        box.value = mode === 'angle' ? String(g.beams[state.lateral]?.refracted_angle ?? '')
            : mode === 'vpa' ? String(state.lateral + 1) : format(lineY(state.lateral), 'value');
    }
    /** The file's reference gain (this group's setup) under the soft gain box. */
    function showRefGain() {
        const ref = currentGroup()?.reference_gain;
        $('ref-gain').hidden = ref === null || ref === undefined;
        if (!$('ref-gain').hidden) $('ref-gain').textContent = `Ref ${(+ref).toFixed(1)} dB`;
    }
    /** A typed beam: the nearest angle, the VPA, or the nearest index position. */
    function goToBeam(text) {
        const g = currentGroup(), v = parseFloat(text);
        if (!g || !Number.isFinite(v)) { showBeam(); return; }
        const mode = beamMode();
        if (mode === 'vpa') { setLateral(Math.round(v) - 1); showBeam(); return; }
        const target = mode === 'angle' ? v : v * unitLength();
        let best = 0;
        for (let i = 0; i < g.shape[1]; i++) {
            const at = mode === 'angle' ? g.beams[i].refracted_angle : lineY(i);
            const bestAt = mode === 'angle' ? g.beams[best].refracted_angle : lineY(best);
            if (Math.abs(at - target) < Math.abs(bestAt - target)) best = i;
        }
        setLateral(best);
        showBeam();
    }

    // ── the weld overlay: the file's weld, or as edited here (kept per file in this browser) ──
    const weld = { shape: null, shift: 0 };   // shape null: the file's own
    const thickness = () => state.info?.specimen?.thickness || 0;
    const fileWeld = () => (state.info?.weld && Object.keys(state.info.weld).length && state.info.weld_outline?.length ? state.info.weld : null);
    const weldKey = () => `analysisWeld:${state.path}`;
    const weldEdited = () => !!weld.shape || Math.abs(weld.shift) > 1e-9;
    // The S-scan's skew view for angle-beam data (90 / 270 button in its head). 90: beams top left to bottom
    // right, the index increasing to the right; 270: top right to bottom left, increasing to the left - so the
    // probe, upstream of the weld, reads negative either way. A view other than the file's skew mirrors the
    // picture. Only the S-scan's axis numbers change; readings keep the file's. Starts at the file's skew; kept per file.
    const angleBeam = () => {
        const g = currentGroup();
        return !!g && g.layout === 'beams' && g.beams.some(b => Math.abs(b.refracted_angle) > 1e-6)
            && [90, 270].includes(Math.round(g.beams[0]?.skew_angle));
    };
    const skewKey = () => `analysisSkew:${state.path}`;
    function applySkew() {
        const on = angleBeam();
        $('skew-toggle').hidden = !on;
        if (!on) { sscan.setSkewView({}); return; }
        const fileSkew = Math.round(currentGroup().beams[0].skew_angle);
        let skew = fileSkew;
        try { skew = +sessionStorage.getItem(skewKey()) || skew; } catch { /* the file's */ }
        state.skewView = skew === 270 ? 270 : 90;
        $('skew-toggle').textContent = `${state.skewView}°`;
        $('skew-toggle').title = `Skew ${state.skewView}° view: beams top ${state.skewView === 90 ? 'left to bottom right' : 'right to bottom left'}, the index increasing to the ${state.skewView === 90 ? 'right' : 'left'} - click for ${state.skewView === 90 ? 270 : 90}°`;
        sscan.setSkewView({ mirror: state.skewView !== fileSkew, labelsLeft: state.skewView === 270 });
    }
    $('skew-toggle').addEventListener('click', () => {
        try { sessionStorage.setItem(skewKey(), String(state.skewView === 90 ? 270 : 90)); } catch { state.skewView = state.skewView === 90 ? 270 : 90; }
        applySkew();
    });

    const weldEditor = new WeldEditor($('weld-editor'), {
        unitLength, format, units: () => units, flipped: () => sscan.flipIndex,
        probeOffset: () => state.info?.probe?.v_offset ?? 0,   // the file's index offset (m)
        onShape: (shape, rebuild) => { weld.shape = shape; saveWeld(); drawWeld(); if (rebuild) showWeldEditor(); },
        onShift: shift => weldShifted(shift, true),
        onReset: () => { weld.shape = null; weld.shift = 0; saveWeld(); applyWeld(); },
        onCreate: () => { weld.shape = defaultWeld(thickness()); saveWeld(); applyWeld(); },
    });

    function loadWeld() {
        let saved = null;
        try { saved = JSON.parse(sessionStorage.getItem(weldKey()) || 'null'); } catch { saved = null; }
        weld.shape = saved?.shape || null;
        weld.shift = Number.isFinite(saved?.shift) ? saved.shift : 0;
    }
    function saveWeld() {
        try {
            if (weldEdited()) sessionStorage.setItem(weldKey(), JSON.stringify({ shape: weld.shape, shift: weld.shift }));
            else sessionStorage.removeItem(weldKey());
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
        $('weld-toggle').hidden = $('caps-toggle').hidden = !shape;
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
        if (!weld.shape) { weldLines(state.info.weld_outline, state.info.weld_caps); return; }
        const mine = ++weldRequest;
        let data;
        try {
            data = await send(urls.weldOutline, 'POST', { weld: weld.shape, thickness: thickness() });
        } catch (e) {
            show(e.message);
            return;
        }
        if (mine === weldRequest) weldLines(data.lines, data.caps);
    }

    /** The outline on the S-scan: the bevel, and the caps when they're asked for (off unless turned on). */
    let shownWeld = { lines: [], caps: [] };
    function weldLines(lines, caps) {
        shownWeld = { lines: lines || [], caps: caps || [] };
        sscan.setWeld([...shownWeld.lines, ...($('show-caps').checked ? shownWeld.caps : [])], $('show-weld').checked);
    }
    try { $('show-caps').checked = localStorage.getItem('analysisWeldCaps') === '1'; } catch { /* off */ }
    $('show-caps').addEventListener('change', e => {
        try { localStorage.setItem('analysisWeldCaps', e.target.checked ? '1' : '0'); } catch { /* not kept */ }
        weldLines(shownWeld.lines, shownWeld.caps);
    });

    /** The centre line moved (typed, nudged, or Alt+dragged on the S-scan; `done` when it settles). */
    function weldShifted(shift, done) {
        const wasEdited = weldEdited();
        weld.shift = shift;
        sscan.setWeldShift(shift);
        weldEditor.setShift(shift);
        $('sscan-readout').textContent = `Index offset ${format((state.info?.probe?.v_offset ?? 0) - shift)}`;   // the probe from the weld centre
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
        showScanPosition();
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
        loadFrameGates();   // the gates along every beam (synced ones follow this line's crossings)
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
        renderGates();   // its lengths use this beam's velocity
        showBeam();
        showRefGain();
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
        const wide = on => (on ? 2.5 : 1);
        const index = isRaster() ? [{ value: c.i_ref, colour: '#f87171', width: wide(selectedIs('cursor', 'i_ref')) },
                                    { value: c.i_meas, colour: '#4ade80', width: wide(selectedIs('cursor', 'i_meas')) }] : [];
        const scanLines = [{ value: c.s_ref, colour: '#f87171', width: wide(selectedIs('cursor', 's_ref')) },
                           { value: c.s_meas, colour: '#4ade80', width: wide(selectedIs('cursor', 's_meas')) },
                           { value: scanPosition(state.scan), colour: CURSOR, width: wide(selectedIs('scan')) }];
        const z = zoneBox();
        const saved = (state.indications || []).filter(i => i.group === state.group && i.status !== 'rejected')
            .map(i => ({ x: scanPosition(i.scan), y: lineY(i.lateral), label: `#${i.number}`,
                         colour: i.status === 'unreviewed' ? '#f59e0b' : '#f472b6' }));
        cview.setCursors({ x: scanLines, y: [{ value: lineY(state.lateral), colour: CURSOR, width: wide(selectedIs('lateral')) }, ...index], contour: state.contour,
                           box: reviewBox() || (z ? z.box : null), marks: [...(z?.mark ? [z.mark] : []), ...saved] });
        drawEcho();
        renderSelection();   // cursors, scan and beam moved: the top bar's value follows
        bview.setCursors({ x: scanLines, y: [{ value: c.u_ref, colour: '#f87171', width: wide(selectedIs('cursor', 'u_ref')) },
                                             { value: c.u_meas, colour: '#4ade80', width: wide(selectedIs('cursor', 'u_meas')) }] });
    }

    // ── whole-file views ──
    let projectionTimer = null, projectionRequest = 0, bscanTimer = null, bscanRequest = 0;
    const wholeShown = () => grid.dataset.layout !== 'A-S';
    function projectionParams() {
        const q = { path: state.path, group: state.group, gain: state.buildGain };
        if (state.gatesEdited) q.gates = gatesParam();
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
        fillFindGates();
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
        state.cscanFull = range;   // the palette bar works within it
        const g = currentGroup();
        const keep = !!state.cscan && state.cscan.scans === scans && state.cscan.lines === lines;
        state.cscan = { data: result.data, scans, lines, mode };
        state.cscanGain = state.buildGain;
        cview.setGain(state.gain - state.cscanGain);
        cview.setImage(result.data, scans, lines, {
            transpose: true, mode, range: paletteRange(), keepView: keep, smooth: !isRaster(),
            axes: { x0: g.axes[0].offset, dx: g.axes[0].resolution, y0: lineY(0), dy: isRaster() ? g.axes[1].resolution : 1 },
        });
        renderReadings();
        $('cscan-range').hidden = mode === 'amplitude';
        renderPaletteBar();
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
            state.cscanFull = [lo, hi];
            cview.setRange(paletteRange());
            renderPaletteBar();
        });
    }

    // The palette bar right of a thickness / depth C-scan: the part of the range typed at its top that
    // the colours are spread over (fractions of it, per C-scan kind) - ends raise the floor / lower the
    // ceiling, the middle shifts it. Values outside take the end colours.
    state.paletteWindows = {};
    const paletteWindow = () => state.paletteWindows[kindSelect.value] || [0, 1];
    function paletteRange() {
        const [lo, hi] = state.cscanFull || [0, 1], [f0, f1] = paletteWindow();
        return [lo + f0 * (hi - lo), lo + f1 * (hi - lo)];
    }
    const paletteBarView = {
        axisRange: () => (state.cscan && state.cscan.mode !== 'amplitude' && state.cscanFull
            ? { full: [...state.cscanFull], shown: paletteRange(), flip: true } : null),
        setAxisRange: (axis, [a, b]) => {
            const [lo, hi] = state.cscanFull, span = hi - lo || 1;
            state.paletteWindows[kindSelect.value] = [Math.max(0, (a - lo) / span), Math.min(1, (b - lo) / span)];
            cview.setRange(paletteRange());
            renderPaletteBar();
        },
        maxZoom: () => 50,
    };
    const drawPaletteBar = ZoomBars.bar(paletteBarView, 'y', $('cscan-palette-bar'),
        'Palette: drag the top to lower the ceiling, the bottom to raise the floor, the middle to shift the colours (double-click: the whole range)');
    function renderPaletteBar() {
        const shown = !!paletteBarView.axisRange();
        $('cscan-palette-bar').hidden = !shown;
        $('cscan-view').classList.toggle('has-palette-bar', shown);
        if (!shown) return;
        // The track: the palette as it's spread now - the low colour under the floor, the high one over the ceiling
        const colours = AnalysisPalette.get('range', rangePalette.value), [f0, f1] = paletteWindow();
        const stops = [];
        for (let k = 0; k <= 8; k++) {
            const i = Math.round(k / 8 * 255) * 4;
            stops.push(`rgb(${colours[i]}, ${colours[i + 1]}, ${colours[i + 2]}) ${((f0 + (f1 - f0) * k / 8) * 100).toFixed(1)}%`);
        }
        $('cscan-palette-bar').style.background = `linear-gradient(to top, ${stops.join(', ')})`;
        drawPaletteBar();
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
        if (state.reviewing) $('review-save').hidden = !cursorsMoved();
    }
    function clearAllCursors() { state.sizing = null; state.contour = null; $('size-note').textContent = ''; setCursors({ ...NO_CURSORS }); }
    $('clear-cursors').addEventListener('click', clearAllCursors);
    /** The cursors each view shows (u depth / sound path, i index, s scan); they're shared, so linked views lose them too. */
    const VIEW_CURSORS = { ascan: ['u'], sscan: ['u', 'i'], bscan: ['s', 'u'], cscan: ['s', 'i'] };
    for (const button of document.querySelectorAll('[data-clear]')) {
        button.addEventListener('click', () => {
            const cleared = {};
            for (const axis of VIEW_CURSORS[button.dataset.clear]) { cleared[`${axis}_ref`] = null; cleared[`${axis}_meas`] = null; }
            if (button.dataset.clear === 'cscan') state.contour = null;   // and its contour box
            setCursors(cleared);
        });
    }

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
    const gateLength = t => format(t * halfVelocity(), 'value');

    const isFloating = gate => gate.float_db !== null && gate.float_db !== undefined;
    /** The edited gates for a ?gates= query; floating ones are set against the page's reference level. */
    const gatesParam = () => JSON.stringify(state.gates.map(g => (isFloating(g) ? { ...g, float_ref: state.refLevel } : g)));

    /** A gate the user added on this page (the file's own gates can't be removed). */
    const addedGate = gate => gate.added || !currentGroup()?.gates.some(f => f.id === gate.id);

    /** The Gates panel: a card per gate - its type, start and width (or depths), threshold, sync, a box's index range. */
    function renderGates() {
        const g = currentGroup();
        const box = $('gate-rows');
        if (!g) return;
        if (!state.gates.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), { className: 'analysis-note', textContent: 'No gates.' }));
            $('gates-edited').hidden = !state.gatesEdited;
            renderAddGates();
            return;
        }
        const el = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };
        const number = (value, onChange) => {
            const input = el('input', { type: 'text', inputMode: 'decimal', value, className: 'form-control form-control-sm mono' });
            input.addEventListener('change', () => {
                const v = parseFloat(input.value);
                if (Number.isFinite(v)) onChange(v);
                gatesChanged();
            });
            return input;
        };
        // A property row: the label (its help as a tooltip) and the control, with its unit after it
        const field = (label, help, control, unit = '') => [
            el('label', { textContent: label, title: help }),
            el('div', { className: 'ana-value' }, control, ...(unit ? [el('span', { className: 'ana-unit', textContent: unit })] : [])),
        ];
        const cards = state.gates.map(gate => {
            const letter = letterOf(gate.name);
            const geometry = gate.geometry || 'SoundPath';
            const depthGate = geometry !== 'SoundPath';
            const card = el('details', { className: `ana-section analysis-gate gate-card-${letter}`, open: true });
            card.dataset.section = `gate:${letter}`;

            // Header row: the letter, the type, remove (buttons in it don't fold the section)
            const types = el('span', { className: 'btn-group btn-group-sm analysis-gate-types', role: 'group' });
            for (const [value, text, help] of [['SoundPath', 'SP', 'Sound path: the same stretch of time on every beam (an arc on a sectorial scan)'],
                                               ['TrueDepth', 'TD', 'True depth: between two depths on every beam; starts from the pulse'],
                                               ['Box', 'Box', 'Box: inside a box of depth and index; beams that miss it have no gate (or zero amplitude, as chosen); starts from the pulse']]) {
                const b = el('button', { type: 'button', className: `btn ${value === geometry ? 'btn-primary' : 'btn-secondary'}`, textContent: text, title: help });
                b.addEventListener('click', e => {
                    e.preventDefault();
                    if (value === geometry) return;
                    convertGate(gate, value);
                    gatesChanged();
                    renderGates();
                });
                types.append(b);
            }
            const tools = el('span', { className: 'ana-tools' }, types);
            if (addedGate(gate)) {
                const remove = el('button', { type: 'button', className: 'ana-icon-btn analysis-gate-remove', title: `Remove ${gate.name}`,
                                              innerHTML: '<i class="bi bi-trash3"></i>' });
                remove.addEventListener('click', e => { e.preventDefault(); removeGate(gate); });
                tools.append(remove);
            }
            card.append(el('summary', {}, el('span', { className: `gate-letter gate-${letter}`, textContent: letter }),
                           el('span', { textContent: gate.name }), tools));

            // Its settings, one row each
            const grid = el('div', { className: 'ana-props' });
            if (depthGate) {
                grid.append(...field('Top', 'Where the gate starts, in true depth', number(format(gate.depth_start, 'value'), v => {
                    const h = gate.depth_end - gate.depth_start;
                    gate.depth_start = v * unitLength(); gate.depth_end = gate.depth_start + h;
                }), units));
                grid.append(...field('Height', 'How deep the gate reaches below its top', number(format(gate.depth_end - gate.depth_start, 'value'), v => {
                    if (v > 0) gate.depth_end = gate.depth_start + v * unitLength();
                }), units));
            } else {
                const from = gate.sync_gate === null || gate.sync_gate === undefined ? 'from the pulse' : 'after the sync gate\'s crossing';
                grid.append(...field('Start', `Sound path ${from}`, number(gateLength(gate.start), v => { gate.start = v * unitLength() / halfVelocity(); }), units));
                grid.append(...field('Width', 'Sound path the gate spans', number(gateLength(gate.length), v => { if (v > 0) gate.length = v * unitLength() / halfVelocity(); }), units));
            }
            grid.append(...field('Threshold', isFloating(gate)
                                     ? `The height set against the ${state.refLevel} % reference level; on each A-scan it keeps that ratio to the peak`
                                     : 'The level a signal must reach to break the gate, % of full screen',
                                 number(String(Math.round(gate.threshold * 10) / 10), v => { gate.threshold = Math.max(0, Math.min(100, v)); }), '%'));
            const detection = el('select', { className: 'form-select form-select-sm' });
            for (const [value, text] of [['edge', 'Edge'], ['peak', 'Peak'], ['maxpeak', 'Max peak']]) detection.add(new Option(text, value));
            detection.value = gate.detection || 'edge';
            detection.addEventListener('change', () => { gate.detection = detection.value; gatesChanged(); renderReadings(); });
            grid.append(...field('Detection', 'Where the gate reads its position (sound path, depth, index, thicknesses, depth / thickness C-scans): Edge - where the signal crosses the threshold; Peak - the first peak after that; Max peak - the highest point in the gate. Its amplitude is always the highest point.', detection));
            const sync = el('select', { className: 'form-select form-select-sm' });
            sync.add(new Option('Pulse', ''));
            for (const other of state.gates) {
                if (other !== gate) sync.add(new Option(`Gate ${letterOf(other.name)}`, other.id, false, gate.sync_gate === other.id));
            }
            if (gate.sync_gate === null || gate.sync_gate === undefined) sync.value = '';
            sync.disabled = depthGate;
            sync.addEventListener('change', () => { gate.sync_gate = sync.value === '' ? null : +sync.value; gatesChanged(); renderGates(); });
            grid.append(...field('Sync', depthGate ? 'Depth and box gates start from the pulse' : 'Starts from the pulse, or another gate\'s crossing', sync));
            if (geometry === 'Box') {
                grid.append(...field('Index from', 'The box\'s side nearer the probe', number(format(gate.index_start, 'value'), v => { gate.index_start = v * unitLength(); }), units));
                grid.append(...field('Index to', 'The box\'s far side', number(format(gate.index_end, 'value'), v => { gate.index_end = v * unitLength(); }), units));
                const outside = el('select', { className: 'form-select form-select-sm' });
                outside.add(new Option('No gate', 'none'));
                outside.add(new Option('0 %', 'zero'));
                outside.value = gate.outside === 'zero' ? 'zero' : 'none';
                outside.addEventListener('change', () => { gate.outside = outside.value; gatesChanged(); });
                grid.append(...field('Missed beams', 'A beam that never passes through the box: no gate at all (the C-scan shows no data, grey), or a gate with no amplitude (0 %, the palette\'s lowest colour)', outside));
            }
            // Floating: the height follows each A-scan's peak at the calibrated ratio, within +/- dB
            const floating = el('input', { type: 'checkbox', className: 'form-check-input', checked: isFloating(gate) });
            floating.addEventListener('change', () => {
                if (floating.checked) { gate.float_db = 6; gate.float_floor = gate.float_floor ?? 10; } else gate.float_db = null;
                gatesChanged();
                renderGates();
            });
            grid.append(el('label', { textContent: 'Floating',
                                      title: `Floating gate: the height keeps its ratio to the reference level (${Math.round(gate.threshold * 10) / 10} % on ${state.refLevel} % = ${Math.round(gate.threshold / state.refLevel * 100)} % of the peak) on every A-scan's own peak, within ± the dB set; peaks under the floor don't break it` }),
                        floating);
            if (isFloating(gate)) {
                grid.append(...field('Float ±', 'How far the height may move from the threshold, up or down',
                                     number(String(gate.float_db), v => { gate.float_db = Math.max(0, Math.min(40, v)); }), 'dB'));
                grid.append(...field('Peak floor', 'A peak under this never breaks the gate (no crossing, no position readings)',
                                     number(String(gate.float_floor ?? 0), v => { gate.float_floor = Math.max(0, Math.min(100, v)); }), '%'));
            }
            card.append(el('div', { className: 'ana-body' }, grid));
            return card;
        });
        box.replaceChildren(...cards);
        shell.rememberSections(box);
        $('gates-edited').hidden = !state.gatesEdited;
        renderAddGates();
    }

    /**
     * Removes a gate added on this page. Gates that started from it start from the pulse instead, where
     * they are now on the cursor's beam.
     */
    function removeGate(gate) {
        for (const other of state.gates) {
            if (other.sync_gate !== gate.id) continue;
            const shown = state.gateResults?.[letterOf(other.name)];
            if (shown?.start !== null && shown?.start !== undefined) other.start = shown.start;
            other.sync_gate = null;
        }
        state.gates = state.gates.filter(x => x !== gate);
        gatesChanged();
        fillKinds();
        renderGates();
    }

    // ── gates on the S-scan ──
    const GATE_COLOURS = { I: '#facc15', A: '#ef4444', B: '#22c55e' };
    const halfV = line => (currentGroup()?.beams[line]?.velocity || 0) / 2;
    const synced = gate => (gate.geometry || 'SoundPath') === 'SoundPath' && gate.sync_gate !== null && gate.sync_gate !== undefined;

    /** A pulse-synced gate's stretch of sound path on each line (as the server's gate_window), for drawing as it's dragged. */
    function localPaths(gate) {
        const g = currentGroup();
        return g.rays.map((r, i) => {
            const geometry = gate.geometry || 'SoundPath';
            if (geometry === 'SoundPath') return [halfV(i) * gate.start, halfV(i) * (gate.start + gate.length)];
            const dz = Math.abs(r.dz) > 1e-9 ? r.dz : 1e-9;
            const [d0, d1] = [gate.depth_start, gate.depth_end].sort((a, b) => a - b);
            let lo = d0 / dz, hi = d1 / dz;
            if (geometry === 'Box') {
                const [i0, i1] = [gate.index_start, gate.index_end].sort((a, b) => a - b);
                if (Math.abs(r.dv) < 1e-12) {
                    if (r.v0 < i0 || r.v0 > i1) return null;
                } else {
                    const [a, b] = [(i0 - r.v0) / r.dv, (i1 - r.v0) / r.dv].sort((x, y) => x - y);
                    lo = Math.max(lo, a); hi = Math.min(hi, b);
                }
            }
            return hi > lo && hi > 0 ? [Math.max(lo, 0), hi] : null;
        });
    }

    /**
     * A synced gate on each line: the server's windows (each beam's own sync crossing), moved by what its
     * start and width have changed since they were fetched - so dragging or wheeling it shows at once.
     */
    function syncedPaths(gate, letter) {
        const base = state.frameGatePaths?.[letter], at = state.frameGateAt?.[letter];
        if (!base) return null;
        if (!at) return base;
        const ds = gate.start - at.start, de = gate.start + gate.length - at.start - at.length;
        return base.map((p, i) => (p ? [p[0] + halfV(i) * ds, p[1] + halfV(i) * de] : null));
    }

    /** The S-scan's gates: drawn from their own settings, or (synced gates) from the server's per-beam windows. */
    function renderSscanGates() {
        const g = currentGroup();
        if (!g) return;
        const list = [];
        for (const gate of state.gates) {
            const letter = letterOf(gate.name);
            if (letter === 'I' && g.synced_to_interface) continue;   // the interface is t = 0 on these files
            const paths = synced(gate) ? syncedPaths(gate, letter) : localPaths(gate);
            if (!paths) continue;
            list.push({ letter, colour: GATE_COLOURS[letter] || '#a78bfa', editable: true, paths,
                        box: gate.geometry === 'Box' ? { i0: gate.index_start, i1: gate.index_end, d0: gate.depth_start, d1: gate.depth_end } : null,
                        depths: gate.geometry === 'TrueDepth' ? { d0: gate.depth_start, d1: gate.depth_end } : null });
        }
        sscan.setGates(list);
    }

    let frameGatesTimer = null, frameGatesRequest = 0;
    /** Every beam's window of the synced gates at this scan line (they follow each beam's own sync crossing). */
    function loadFrameGates(delay = 0) {
        clearTimeout(frameGatesTimer);
        frameGatesTimer = setTimeout(async () => {
            if (!state.info || !$('show-sscan-gates').checked || !state.gates.some(synced)) { state.frameGatePaths = null; renderSscanGates(); return; }
            const mine = ++frameGatesRequest;
            // The synced gates' settings these windows are for (syncedPaths moves them by later changes)
            const at = Object.fromEntries(state.gates.filter(synced).map(x => [letterOf(x.name), { start: x.start, length: x.length }]));
            const query = { path: state.path, group: state.group, scan: state.scan, gain: state.gain };
            if (state.gatesEdited) query.gates = gatesParam();
            try {
                const data = await NdeClient.readings({ readings: urls.frameGates }, query);
                if (mine !== frameGatesRequest) return;
                state.frameGatePaths = data.paths;
                state.frameGateAt = at;
            } catch {
                state.frameGatePaths = null;
            }
            renderSscanGates();
        }, delay);
    }
    try { $('show-sscan-gates').checked = localStorage.getItem('analysisSscanGates') !== '0'; } catch { /* on */ }
    sscan.setShowGates($('show-sscan-gates').checked);
    $('show-sscan-gates').addEventListener('change', e => {
        try { localStorage.setItem('analysisSscanGates', e.target.checked ? '1' : '0'); } catch { /* not kept */ }
        sscan.setShowGates(e.target.checked);
        loadFrameGates();
    });

    /** A gate edited by dragging it on the S-scan: deltas (m) since the press, applied to its settings then. */
    function dragGateOnSscan(letter, part, { dx, dy, dsp, line }) {
        const gate = gateByLetter(letter), s = gateSnapshot;
        if (!gate || !s) return;
        const g = currentGroup();
        const least = g.axes[2].resolution * halfV(state.lateral);   // a sample's worth of sound path
        const geometry = gate.geometry || 'SoundPath';
        if (geometry === 'SoundPath') {
            const dt = dsp / (halfV(line ?? state.lateral) || 1);
            const minimum = g.axes[2].resolution;
            if (part === 'move') gate.start = s.start + dt;
            else if (part === 'start') gate.start = s.start + dt;   // the end moves with it: the width stays
            else if (part === 'end') gate.length = Math.max(minimum, s.length + dt);
        } else {
            const dd = part === 'move' ? dy : dsp * (g.rays[line ?? state.lateral]?.dz || 1);
            const vertical = { start: 'depth_start', end: 'depth_end', d0: 'depth_start', d1: 'depth_end' }[part];
            if (part === 'move') {
                gate.depth_start = s.depth_start + dy; gate.depth_end = s.depth_end + dy;
                if (geometry === 'Box') { gate.index_start = s.index_start + dx; gate.index_end = s.index_end + dx; }
            } else if (geometry === 'TrueDepth' && (part === 'start' || part === 'd0')) {   // the top carries the bottom: the height stays
                const d = part === 'd0' ? dy : dd;
                gate.depth_start = s.depth_start + d; gate.depth_end = s.depth_end + d;
            } else if (vertical) {
                gate[vertical] = s[vertical] + (part.startsWith('d') ? dy : dd);
                if (gate.depth_end - gate.depth_start < least && part !== 'd0' && part !== 'd1') {
                    if (vertical === 'depth_start') gate.depth_start = gate.depth_end - least; else gate.depth_end = gate.depth_start + least;
                }
            } else if (part === 'i0' || part === 'i1') {
                const key = part === 'i0' ? 'index_start' : 'index_end';
                gate[key] = s[key] + dx;
            }
        }
        renderSscanGates();
        gatesChanged(20);
        previewDraggedGate(letter);
    }

    /**
     * A gate changed to another type, keeping where it is on the cursor's beam: its stretch of sound path
     * there becomes the depths (and, for a box, the index positions it spans) or back again.
     */
    function convertGate(gate, geometry) {
        const g = currentGroup();
        const r = g.rays[state.lateral], hv = halfV(state.lateral) || 1;
        const old = gate.geometry || 'SoundPath';
        if (old === geometry) return;
        let sp0, sp1;
        if (old === 'SoundPath') {
            const shown = state.gateResults?.[letterOf(gate.name)];   // where it is on this beam now (synced gates too)
            const t0 = shown?.start ?? gate.start, t1 = shown?.end ?? gate.start + gate.length;
            sp0 = t0 * hv; sp1 = t1 * hv;
        } else {
            const p = localPaths(gate)[state.lateral];
            const dz = r.dz || 1;
            [sp0, sp1] = p || [gate.depth_start / dz, gate.depth_end / dz];
        }
        gate.geometry = geometry;
        if (geometry === 'SoundPath') {
            gate.start = sp0 / hv; gate.length = Math.max(g.axes[2].resolution, (sp1 - sp0) / hv);
            return;
        }
        gate.sync_gate = null;   // depth and box gates start from the pulse
        gate.depth_start = sp0 * r.dz; gate.depth_end = sp1 * r.dz;
        if (geometry === 'Box') {
            const a = r.v0 + sp0 * r.dv, b = r.v0 + sp1 * r.dv;
            const half = Math.max(Math.abs(b - a) / 2, 0.005);   // at least 5 mm each side (a 0 deg line is a point)
            const mid = (a + b) / 2;
            gate.index_start = mid - half; gate.index_end = mid + half;
        }
    }

    /** Buttons to add the gates a file doesn't have (I, A, B), set up the usual way. */
    function renderAddGates() {
        const box = $('add-gates');
        const have = new Set(state.gates.map(x => letterOf(x.name)));
        const buttons = ['I', 'A', 'B'].filter(L => !have.has(L)).map(L => {
            const b = Object.assign(document.createElement('button'), { type: 'button', className: 'btn btn-sm btn-secondary',
                                                                       innerHTML: `<i class="bi bi-plus-lg"></i> ${L}`,
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
        const gate = { id, name: `Gate ${letter}`, threshold: letter === 'I' ? 35 : 20, trigger: 'Crossing', sync_gate: null, added: true, detection: 'edge',
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
        renderSelection();
        renderSscanGates();
        if (!document.activeElement?.closest('#gate-rows')) renderGates();
        $('gates-edited').hidden = false;
        if (state.draggingGate) {   // drawn here at once; the server catches up when it's let go (gateDragEnded)
            return;
        }
        loadFrameGates(150);
        scheduleReadings(delay);
        scheduleProjections(700);   // the C-scan follows the gates once they settle
    }

    $('reset-gates').addEventListener('click', () => {
        state.gates = fileGates(currentGroup());
        state.gatesEdited = false;
        save();
        renderGates();
        renderSscanGates();
        loadFrameGates();
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
        if (state.gatesEdited) query.gates = gatesParam();
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
        state.gateResults = data.gates;
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
                const shown = name.replace(/([A-Z])([/^])/g, (all, letter) => (gateByLetter(letter) ? `${letter}${detectionMark(letter)}` : all));
                const how = DETECTION_NAMES[gateByLetter(name.match(/([A-Z])[/^]/)?.[1])?.detection || ''];
                rows.push(Object.assign(document.createElement('dt'), {
                    textContent: shown, title: [READING_NAMES[name] || '', how ? `(gate at its ${how})` : ''].filter(Boolean).join(' ') }));
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
            if (r.auto || r.contour) {
                if (has(r.height)) add('Height', format(r.height));
                if (has(r.width)) add('Width', format(r.width));
                if (has(r.depth)) add('Depth', format(r.depth));
                if (has(r.axial)) add(isRaster() ? 'Index' : 'PA^', format(r.axial));
            }
            if (has(r.peak_amplitude)) add('Peak%', `${r.peak_amplitude.toFixed(1)} %`);
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
            if ((state.sizing.auto || state.sizing.contour) && has(state.sizing.height)) out.Height = state.sizing.height;
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

    /** Contour sizing: the strongest signal inside the Alt+drag box on the C-scan, sized by the drop chosen (as a found one is). */
    async function sizeInBox() {
        const b = state.contour, cs = state.cscan;
        if (!b || !cs || !state.info) return;
        const [c0, r0] = cscanCell(Math.min(b.x0, b.x1), Math.min(b.y0, b.y1));
        const [c1, r1] = cscanCell(Math.max(b.x0, b.x1), Math.max(b.y0, b.y1));
        const note = $('size-note');
        if (c1 < 0 || r1 < 0 || c0 >= cs.scans || r0 >= cs.lines || (c0 === c1 && r0 === r1)) {
            state.contour = null;   // a click, or outside the data: no box
            linkCursors();
            return;
        }
        const [gate, kind] = kindSelect.value.split(':');
        const method = $('size-method').value === 'threshold' ? '6' : $('size-method').value;
        note.textContent = 'Sizing in the box…';
        let response, data;
        try {
            response = await fetch(`${urls.size}?${new URLSearchParams({ ...projectionParams(), scan: state.scan, lateral: state.lateral,
                                                                          gate: kind === 'amplitude' ? gate : 'A', method,
                                                                          box: [c0, c1, r0, r1].join(',') })}`);
            data = await response.json();
        } catch {
            note.textContent = "Couldn't size: is the server running?";
            return;
        }
        if (response.status === 409) {   // the whole-file data isn't built yet: build it, then size
            note.textContent = 'Reading the whole file first…';
            if (await waitForBuild()) return sizeInBox();
            note.textContent = "Couldn't read the whole file.";
            return;
        }
        if (!response.ok) { note.textContent = data.error || "Couldn't size in the box."; return; }
        state.sizing = data;
        note.textContent = data.saturated ? 'Saturated peak: the sizing may be short.' : '';
        setCursors({ ...NO_CURSORS, ...sizingCursors(data) });
        if (data.peak_scan !== state.scan) setScan(data.peak_scan);
        if (data.peak_line !== state.lateral) setLateral(data.peak_line);
    }

    // ── echo-dynamic: the gate's highest amplitude along the scan, under the C-scan ──
    const echo = $('echo-strip');
    let echoDrag = null;
    try { $('show-echo').checked = localStorage.getItem('analysisEcho') !== '0'; } catch { /* on */ }
    $('show-echo').addEventListener('change', e => {
        try { localStorage.setItem('analysisEcho', e.target.checked ? '1' : '0'); } catch { /* not kept */ }
        drawEcho();
    });
    /** The C-scan lines the curve takes the most of: the box's, the sized indication's, else the cursor's. */
    function echoLines() {
        const cs = state.cscan, b = state.contour, s = state.sizing;
        const clamp = r => Math.max(0, Math.min(cs.lines - 1, r));
        if (b) return [clamp(cscanCell(0, Math.min(b.y0, b.y1))[1]), clamp(cscanCell(0, Math.max(b.y0, b.y1))[1])];
        if (s && (s.auto || s.contour) && has(s.line_lo) && has(s.line_hi)) return [clamp(s.line_lo), clamp(s.line_hi)];
        return [state.lateral, state.lateral];
    }
    /** Strip x (device pixels) of a scan position, through the C-scan's view. */
    const echoX = v => cview.toScreen(v, 0)[0] * echo.width / (cview.overlay.width || 1);
    function drawEcho() {
        const cs = state.cscan;
        const show = $('show-echo').checked && wholeShown() && cs?.mode === 'amplitude' && cview.hasImage;
        echo.hidden = !show;
        if (!show) return;
        const ratio = window.devicePixelRatio || 1;
        const rect = echo.getBoundingClientRect();
        const w = Math.max(1, Math.round(rect.width * ratio)), h = Math.max(1, Math.round(rect.height * ratio));
        if (echo.width !== w || echo.height !== h) { echo.width = w; echo.height = h; }
        const ctx = echo.getContext('2d');
        ctx.clearRect(0, 0, w, h);
        const pad = 6 * ratio, sy = v => h - pad - Math.min(100, Math.max(0, v)) / 100 * (h - 2 * pad);
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
        ctx.lineWidth = ratio;
        for (const v of [0, 50, 100]) { ctx.beginPath(); ctx.moveTo(0, sy(v)); ctx.lineTo(w, sy(v)); ctx.stroke(); }
        // The curve: the most of the lines at each scan position, at the soft gain shown
        const [r0, r1] = echoLines();
        const k = Math.pow(10, (state.gain - state.cscanGain) / 20);
        ctx.strokeStyle = '#fde047';
        ctx.lineWidth = 1.4 * ratio;
        ctx.beginPath();
        let started = false, peak = -1;
        for (let i = 0; i < cs.scans; i++) {
            let top = -1;
            for (let j = r0; j <= r1; j++) { const v = cs.data[i * cs.lines + j]; if (v > top) top = v; }
            if (top < 0) { started = false; continue; }
            const x = echoX(scanPosition(i)), v = top * k;
            if (x >= 0 && x <= w && v > peak) peak = v;
            if (!started) { ctx.moveTo(x, sy(v)); started = true; } else ctx.lineTo(x, sy(v));
        }
        ctx.stroke();
        // The drop level under the sized peak (or the highest point on show)
        const s = state.sizing;
        const drop = s?.method && s.method !== 'threshold' ? +s.method : +$('size-method').value || 6;
        const top = s && has(s.peak_amplitude) && has(s.base_gain) ? s.peak_amplitude * Math.pow(10, (state.gain - s.base_gain) / 20) : peak;
        if (top > 0) {
            const y = sy(top * Math.pow(10, -drop / 20));
            ctx.save();
            ctx.setLineDash([5 * ratio, 4 * ratio]);
            ctx.strokeStyle = ctx.fillStyle = '#94a3b8';
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
            ctx.font = `${10 * ratio}px Inter, Arial, sans-serif`;
            ctx.fillText(`−${drop} dB`, 4 * ratio, y - 3 * ratio);
            ctx.restore();
        }
        // The ends (scan cursors, draggable here) and the scan cursor
        for (const [key, colour] of [['s_ref', '#f87171'], ['s_meas', '#4ade80'], [null, CURSOR]]) {
            const v = key ? state.cursors[key] : scanPosition(state.scan);
            if (!has(v)) continue;
            const x = echoX(v);
            ctx.strokeStyle = colour; ctx.lineWidth = (key ? 1.5 : 1) * ratio;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        }
    }
    /** Scan position (m) under the pointer on the strip, through the C-scan's view. */
    function echoScan(e) {
        const rect = echo.getBoundingClientRect();
        const [cx, , vw] = cview.currentView();
        return cx + ((e.clientX - rect.left) / rect.width - 0.5) * vw;
    }
    /** The end cursor within a few pixels of the pointer on the strip, or null. */
    function echoEnd(e) {
        const rect = echo.getBoundingClientRect();
        const px = (e.clientX - rect.left) * echo.width / (rect.width || 1);
        const ratio = window.devicePixelRatio || 1;
        return ['s_ref', 's_meas'].filter(k => has(state.cursors[k]))
            .map(k => [k, Math.abs(echoX(state.cursors[k]) - px)])
            .filter(([, d]) => d < 6 * ratio).sort((a, b) => a[1] - b[1])[0]?.[0] || null;
    }
    echo.addEventListener('pointerdown', e => {
        if (e.button !== 0 || !state.cscan) return;
        echo.setPointerCapture(e.pointerId);
        echoDrag = echoEnd(e);
        select(echoDrag ? { kind: 'cursor', key: echoDrag } : { kind: 'scan' });
        if (echoDrag) return;
        const [column] = cscanCell(echoScan(e), 0);
        if (column >= 0 && column < state.cscan.scans && column !== state.scan) setScan(column);
    });
    echo.addEventListener('pointermove', e => {
        if (echoDrag) { setCursors({ [echoDrag]: echoScan(e) }); return; }
        echo.style.cursor = echoEnd(e) ? 'ew-resize' : 'crosshair';
    });
    for (const type of ['pointerup', 'pointercancel']) echo.addEventListener(type, () => { echoDrag = null; });
    // Double-click: fit the C-scan (the strip follows its zoom), like double-clicking the C-scan itself
    echo.addEventListener('dblclick', () => { cview.view = null; cview.draw(); cview.options.onViewChange?.(cview); });
    new ResizeObserver(() => drawEcho()).observe(echo);

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

    const STATUS_TEXT = { unreviewed: 'To review', accepted: 'Accepted', rejected: 'Rejected' };
    const STATUS_SHORT = { unreviewed: 'Review', accepted: 'OK', rejected: 'No' };
    const shownIndications = () => (state.indications || []).filter(i => state.filter === 'all' || i.status === state.filter)
        .sort((a, b) => a.group - b.group || (a.sizing?.scan_start ?? a.scan_position ?? 0) - (b.sizing?.scan_start ?? b.scan_position ?? 0) || a.lateral - b.lateral);

    // ── grading against the acceptance criteria of 100-UT-020 (Rev 9): criteria.js ──
    let gradeCriteria = '';
    try { gradeCriteria = localStorage.getItem('analysisCriteria') || ''; } catch { /* none */ }
    $('grade-criteria').value = gradeCriteria;
    $('grade-criteria').addEventListener('change', e => {
        gradeCriteria = e.target.value;
        try { localStorage.setItem('analysisCriteria', gradeCriteria); } catch { /* not kept */ }
        renderIndications();
    });
    /** An indication's peak at the file's reference gain (% FSH), or null; Infinity when saturated. */
    const amplitudeAtReference = item => AnalysisCriteria.atReference(item, currentGroup());
    /** {grade: 'fail' | 'assess' | 'pass', reason} for the chosen criteria, or null when none chosen. */
    function gradeOf(item) {
        const z = item.sizing || {}, r = item.readings || {};
        return AnalysisCriteria.grade(gradeCriteria, {
            amplitude: amplitudeAtReference(item),
            reference: currentGroup()?.reference_amplitude || state.refLevel || 80,
            length: z.length ?? r.Length ?? (has(r['S(m-r)']) ? Math.abs(r['S(m-r)']) : null),
            thickness: state.info?.specimen?.thickness,
        }, format);
    }

    /** The Indications panel: the review card, then a row each (# · scan · length · height · depth · PA^ · A% · status). */
    function renderIndications() {
        if (!$('clear-finds-menu').hidden) showClearMenu(true);   // its counts follow the list
        const all = state.indications || [];
        const list = shownIndications();
        $('indication-count').textContent = all.length;
        $('indication-count').hidden = !all.length;
        const left = all.filter(i => i.status === 'unreviewed').length;
        const reviewed = all.some(i => i.source === 'auto') ? (left ? `${all.length - left} of ${all.length} reviewed` : `All ${all.length} reviewed`) : '';
        // With criteria chosen: how many fail / need characterising / pass (rejected indications left out)
        const grades = { fail: 0, assess: 0, pass: 0 };
        for (const i of all) { const g = i.status !== 'rejected' && gradeOf(i); if (g) grades[g.grade] += 1; }
        $('review-progress').replaceChildren(reviewed);
        if (gradeCriteria && all.length) {
            const summary = Object.assign(document.createElement('span'), { className: 'analysis-grade-summary' });
            summary.append(reviewed ? ' · ' : '', ...[['fail', 'fail'], ['assess', 'to characterise'], ['pass', 'pass']].flatMap(([k, text], n) => [
                n ? ' · ' : '', Object.assign(document.createElement('span'), { className: k, textContent: `${grades[k]} ${text}` })]));
            $('review-progress').append(summary);
        }
        for (const b of $('review-filter').querySelectorAll('[data-filter]')) {
            b.className = `btn ${b.dataset.filter === state.filter ? 'btn-primary' : 'btn-secondary'}`;
        }
        renderReview();
        const box = $('indication-rows');
        if (!list.length) {
            box.replaceChildren(Object.assign(document.createElement('p'), { className: 'analysis-note',
                textContent: all.length ? 'None to show here.' : 'None yet.' }));
            return;
        }
        const table = document.createElement('table');
        table.className = 'analysis-indication-table';
        const head = table.createTHead().insertRow();
        const raster = isRaster();
        for (const h of ['#', 'Scan', 'Length', raster ? 'Width' : 'Height', 'Depth', raster ? 'Index' : 'PA^', 'A%', '', '']) {
            head.append(Object.assign(document.createElement('th'), {
                textContent: h, title: h === 'PA^' ? "Axial position: the peak from the probe's index offset (OmniPC's Index)" : '' }));
        }
        const body = table.createTBody();
        const value = v => (has(v) ? format(Math.abs(v), 'value') : '-');
        for (const item of list) {
            const tr = body.insertRow();
            const current = item.id === state.reviewing || (!state.reviewing && item.scan === state.scan && item.lateral === state.lateral);
            tr.className = [current ? 'is-current' : '', item.status === 'rejected' ? 'is-rejected-row' : ''].join(' ').trim();
            const grade = item.status !== 'rejected' ? gradeOf(item) : null;
            if (grade) tr.dataset.grade = grade.grade;
            const r = item.readings || {}, z = item.sizing || {};
            const depth = z.depth ?? r['DA^'] ?? r['A/-I/'] ?? r['TminZ'];
            const length = z.length ?? r.Length ?? r.Width ?? r['S(m-r)'];
            const cursors = item.cursors || {};
            const across = raster ? (z.width ?? r.Width)
                : (z.height ?? (has(cursors.u_ref) && has(cursors.u_meas) ? cursors.u_meas - cursors.u_ref : null));
            const where = raster ? (z.axial ?? item.index_position) : (z.axial ?? r['PA^']);
            const cells = [item.number, format(z.scan_start ?? item.scan_position, 'value'), value(length), value(across), value(depth),
                           has(where) ? format(where, 'value') : '-', r['A%'] === undefined ? '-' : r['A%'].toFixed(1)];
            for (const text of cells) tr.insertCell().textContent = text;
            if (grade) tr.cells[0].title = grade.reason;
            // The status as one mark (its words in the tooltip): • to review, ✓ accepted, ✕ rejected, + added by hand
            const added = item.source !== 'auto' && item.status === 'accepted';
            const mark = Object.assign(document.createElement('span'), {
                className: `analysis-status-mark is-${item.status}`,
                textContent: added ? '+' : { unreviewed: '•', accepted: '✓', rejected: '✕' }[item.status] || '•' });
            const notes = [item.source === 'auto' ? STATUS_TEXT[item.status] : 'Added by hand'];
            if (z.edited) { mark.textContent += ' ✎'; notes.push('Sizing corrected by hand'); }
            if (z.saturated) { mark.textContent += ' !'; notes.push('Saturated peak: the sizing may be short'); }
            mark.title = notes.join('. ');
            tr.insertCell().append(mark);
            const remove = Object.assign(document.createElement('button'), { type: 'button', className: 'ana-icon-btn',
                                                                           title: 'Delete this indication', innerHTML: '<i class="bi bi-trash3"></i>' });
            remove.addEventListener('click', async e => {
                e.stopPropagation();
                try { await send(indicationUrl(item.id), 'DELETE'); } catch (err) { show(err.message); return; }
                if (state.reviewing === item.id) state.reviewing = null;
                loadIndications();
            });
            tr.insertCell().append(remove);
            tr.addEventListener('click', () => goTo(item));
            // The comment on its own line under the row
            const comment = Object.assign(document.createElement('input'), { type: 'text', className: 'form-control', value: item.comment || '',
                                                                            placeholder: 'Comment' });
            comment.addEventListener('click', e => e.stopPropagation());
            comment.addEventListener('change', () => send(indicationUrl(item.id), 'POST', { comment: comment.value })
                .then(saved => { item.comment = saved.comment; }).catch(e => show(e.message)));
            const note = body.insertRow();
            note.className = `analysis-indication-note${current ? ' is-current' : ''}`;
            note.hidden = !current && !item.comment;   // the comment line only where there's one, or on the current row
            const cell = note.insertCell();
            cell.colSpan = 9;
            cell.append(comment);
        }
        box.replaceChildren(table);
        box.querySelector('tr.is-current')?.scrollIntoView({ block: 'nearest' });
    }
    for (const b of $('review-filter').querySelectorAll('[data-filter]')) {
        b.addEventListener('click', () => { state.filter = b.dataset.filter; renderIndications(); });
    }

    /** The card of the indication being reviewed: what it measured, and Keep cursors when they were moved off it. */
    function renderReview() {
        const item = reviewed();
        $('review-card').hidden = !item;
        if (!item) return;
        const s = item.sizing, raster = isRaster();
        $('review-title').textContent = `Indication #${item.number}`;
        const statusMark = $('review-status');
        statusMark.className = `analysis-review-status is-${item.status}`;
        statusMark.textContent = STATUS_TEXT[item.status] + (s.edited ? ' · corrected' : '');
        const rows = [
            ['Sizing', s.edited ? 'by hand' : `−${s.method} dB`], ['Scan', `${format(s.scan_start, 'value')}–${format(s.scan_end, 'value')}`],
            ['Length', format(s.length)],
            raster ? ['Width', format(s.width)] : ['Height', format(s.height)],
            ['Depth', format(s.depth)], [raster ? 'Index' : 'PA^', format(s.axial)],
            [raster ? 'Index span' : 'Axial span', `${format(s.axial_start, 'value')}–${format(s.axial_end, 'value')}`],
            ['Peak', `${(s.peak_amplitude ?? 0).toFixed(1)} %`], ['To 80 %', `${s.gain_db >= 0 ? '+' : ''}${(s.gain_db ?? 0).toFixed(1)} dB`],
            ...(raster ? [] : [['Angle', `${s.angle}°`], ['Leg', String(s.leg ?? '')]]),
            ...(s.saturated ? [['Saturated', 'sizing may be short']] : []),
        ];
        $('review-values').replaceChildren(...rows.map(([name, text]) => {
            const div = document.createElement('div');
            if (name === 'Saturated') div.className = 'is-warning';
            div.append(Object.assign(document.createElement('dt'), { textContent: name }), Object.assign(document.createElement('dd'), { textContent: text }));
            return div;
        }));
        for (const b of $('review-card').querySelectorAll('[data-resize]')) b.classList.toggle('active', b.dataset.resize === s.method && !s.edited);
        $('review-save').hidden = !cursorsMoved();
    }

    /** Whether the reference / measure cursors were moved off the reviewed indication's sizing. */
    function cursorsMoved() {
        const item = reviewed();
        if (!item) return false;
        const want = sizingCursors(item.sizing), c = state.cursors;
        return Object.keys(want).some(k => (has(want[k]) || has(c[k])) && !(has(want[k]) && has(c[k]) && Math.abs(want[k] - c[k]) < 1e-7));
    }

    /** The sizing taken from the cursors as they are now (S, or on Accept after moving them). */
    async function keepCursors() {
        const item = reviewed();
        if (!item || !cursorsMoved()) return item;
        const c = state.cursors, raster = isRaster(), probe = state.info?.probe?.v_offset ?? 0;
        const manual = { scan_start: c.s_ref, scan_end: c.s_meas };
        if (!raster) Object.assign(manual, { view_top: c.u_ref, view_bottom: c.u_meas });   // as drawn: unfolded
        if (has(c.i_ref)) manual.axial_start = raster ? c.i_ref : c.i_ref - probe;
        if (has(c.i_meas)) manual.axial_end = raster ? c.i_meas : c.i_meas - probe;
        let saved;
        try {
            saved = await send(resizeUrl(item.id), 'POST', { manual });
        } catch (e) {
            show(e.message);
            return null;
        }
        Object.assign(item, saved);
        renderIndications();
        return item;
    }
    const resizeUrl = id => `${urls.resize.replace('/0/', `/${id}/`)}?${new URLSearchParams(projectionParams())}`;

    /** Accept (or reject) the indication being reviewed - moved cursors become its sizing - then on to the next to review. */
    async function review(status) {
        let item = reviewed();
        if (!item) return;
        if (status === 'accepted') item = await keepCursors();
        if (!item) return;
        try {
            Object.assign(item, await send(indicationUrl(item.id), 'POST', { status }));
        } catch (e) {
            show(e.message);
            return;
        }
        const next = nextToReview(item);
        if (next) { goTo(next); return; }
        $('find-note').textContent = 'Every found indication is reviewed.';
        renderIndications();
    }
    /** The next indication still to review after `item` (along the scan, round to the start), else null. */
    function nextToReview(item) {
        const list = [...(state.indications || [])].sort((a, b) => a.group - b.group || (a.sizing?.scan_start ?? 0) - (b.sizing?.scan_start ?? 0));
        const at = list.indexOf(item);
        return [...list.slice(at + 1), ...list.slice(0, at)].find(i => i.status === 'unreviewed') || null;
    }

    /** POST that waits for the whole-file build once if the server is still reading the file (409). */
    async function postBuilt(url, body, note) {
        for (let attempt = 0; attempt < 2; attempt++) {
            const response = await fetch(url, { method: 'POST', body: JSON.stringify(body),
                                                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrf()) } });
            const data = await response.json().catch(() => ({}));
            if (response.status === 409 && attempt === 0) {
                if (note) note.textContent = 'Reading the whole file first…';
                if (await waitForBuild()) continue;
                throw new Error("Couldn't read the whole file.");
            }
            if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
            return data;
        }
        throw new Error("Couldn't read the whole file.");
    }

    /** Size the reviewed indication again at another dB drop. */
    async function resize(method) {
        const item = reviewed();
        if (!item) return;
        try {
            Object.assign(item, await postBuilt(resizeUrl(item.id), { method }));
        } catch (e) {
            show(e.message);
            return;
        }
        await goTo(item);
    }

    // ── clear indications (Find box): which ones, how many on this group, then confirm ──
    const CLEAR_CHOICES = [
        ['unreviewed', 'Found, to review', i => i.source === 'auto' && i.status === 'unreviewed'],
        ['rejected', 'Rejected', i => i.status === 'rejected'],
        ['found', 'All found', i => i.source === 'auto'],
        ['all', 'Everything', () => true],
    ];
    let clearChoice = null;
    function renderClearChoices() {
        const here = (state.indications || []).filter(i => i.group === state.group);
        $('clear-finds-choices').replaceChildren(...CLEAR_CHOICES.map(([which, text, test]) => {
            const count = here.filter(test).length;
            const b = Object.assign(document.createElement('button'), {
                type: 'button', className: `btn btn-sm ${clearChoice === which ? 'btn-primary' : 'btn-secondary'}`,
                textContent: `${text} (${count})`, disabled: !count });
            b.addEventListener('click', () => {
                clearChoice = which;
                $('clear-finds-question').textContent = which === 'all'
                    ? `Delete all ${count} indication${count === 1 ? '' : 's'} on this group, added ones too?`
                    : `Delete ${count} ${text.toLowerCase()} indication${count === 1 ? '' : 's'} on this group?`;
                $('clear-finds-confirm').hidden = false;
                renderClearChoices();
            });
            return b;
        }));
    }
    function showClearMenu(open) {
        clearChoice = null;
        $('clear-finds-menu').hidden = !open;
        $('clear-finds-confirm').hidden = true;
        $('clear-finds').setAttribute('aria-expanded', String(open));
        if (open) renderClearChoices();
    }
    $('clear-finds').addEventListener('click', () => showClearMenu($('clear-finds-menu').hidden));
    $('clear-finds-no').addEventListener('click', () => showClearMenu(false));
    $('clear-finds-yes').addEventListener('click', async () => {
        if (!clearChoice || !state.path) return;
        let data;
        try {
            data = await send(urls.clearIndications, 'POST', { path: state.path, group: state.group, which: clearChoice });
        } catch (e) {
            $('find-note').textContent = e.message;
            return;
        }
        state.indications = data.indications;
        if (state.reviewing && !state.indications.some(i => i.id === state.reviewing)) {
            state.reviewing = null;
            if (Math.abs(state.gain - state.buildGain) > 1e-9) setGain(state.buildGain);   // back from its review gain
        }
        $('find-note').textContent = `Deleted ${data.deleted} indication${data.deleted === 1 ? '' : 's'}.`;
        showClearMenu(false);
        renderIndications();
        linkCursors();
    });

    // ── find indications ──
    function fillFindGates() {
        const letters = state.gates.map(x => letterOf(x.name)).filter(L => !(L === 'I' && currentGroup()?.synced_to_interface));
        const select = $('find-gate');
        const was = select.value;
        select.replaceChildren(...letters.map(L => new Option(`Gate ${L}`, L)));
        select.value = letters.includes(was) ? was : letters.includes('A') ? 'A' : letters[0] || '';
        $('find-min-unit').textContent = units;
    }

    async function findIndications() {
        if (!state.info) return;
        const note = $('find-note');
        const threshold = parseFloat($('find-threshold').value);
        const minimum = parseFloat($('find-min').value);
        const body = { gate: $('find-gate').value || 'A', method: $('find-method').value,
                       merge_gap: Math.max(0, parseInt($('find-gap').value, 10) || 0),
                       min_length: Number.isFinite(minimum) && minimum > 0 ? minimum * unitLength() : 0 };
        if (Number.isFinite(threshold)) body.threshold = threshold;
        $('find-now').disabled = true;
        note.textContent = 'Finding…';
        let data;
        try {
            data = await postBuilt(`${urls.detect}?${new URLSearchParams(projectionParams())}`, body, note);
        } catch (e) {
            note.textContent = e.message;
            return;
        } finally {
            $('find-now').disabled = false;
            $('size-note').textContent = '';
        }
        state.indications = data.indications;
        const parts = [`Found ${data.found} indication${data.found === 1 ? '' : 's'} to review`];
        if (data.kept) parts.push(`${data.kept} kept (reviewed or added)`);
        if (data.overlapping) parts.push(`${data.overlapping} on top of kept ones left out`);
        if (data.skipped.length) parts.push(`${data.skipped.length} couldn't be sized`);
        note.textContent = `${parts.join(' · ')}.`;
        state.filter = 'all';
        linkCursors();
        const first = shownIndications().find(i => i.status === 'unreviewed' && i.group === state.group);
        if (first) goTo(first);
        else renderIndications();
    }
    $('find-now').addEventListener('click', findIndications);
    $('review-accept').addEventListener('click', () => review('accepted'));
    $('review-reject').addEventListener('click', () => review('rejected'));
    $('review-save').addEventListener('click', keepCursors);
    $('review-prev').addEventListener('click', () => stepIndication(-1));
    $('review-next').addEventListener('click', () => stepIndication(1));
    for (const b of $('review-card').querySelectorAll('[data-resize]')) b.addEventListener('click', () => resize(b.dataset.resize));

    async function goTo(item) {
        if (item.group !== state.group) await setGroup(item.group, item.scan, item.lateral);
        const auto = item.sizing?.auto;
        state.reviewing = auto ? item.id : null;
        state.sizing = item.sizing && item.sizing.length !== undefined ? item.sizing : null;
        setCursors({ ...NO_CURSORS, ...(auto ? sizingCursors(item.sizing) : item.cursors || {}) });
        if (auto) setGain((item.sizing.base_gain || 0) + (item.sizing.gain_db || 0), true);   // at its 80 %
        else if (Math.abs(state.gain - state.buildGain) > 1e-9) setGain(state.buildGain);    // back from a review gain
        await setScan(item.scan);
        setLateral(item.lateral, true);
        renderIndications();
    }

    /** A found indication's sizing as the reference / measure cursors: its scan ends, its top and bottom, its axial extent. */
    function sizingCursors(s) {
        const probe = state.info?.probe?.v_offset ?? 0;
        const raster = isRaster();
        const index = v => (has(v) ? (raster ? v : v + probe) : null);   // PA^ back to the index position
        return { s_ref: s.scan_start ?? null, s_meas: s.scan_end ?? null,
                 u_ref: raster ? null : s.view_top ?? s.top ?? null, u_meas: raster ? null : s.view_bottom ?? s.bottom ?? null,
                 i_ref: index(s.axial_start), i_meas: index(s.axial_end) };
    }

    /** The C-scan box of the indication being reviewed: its sized length across its beams / index lines. */
    function reviewBox() {
        const item = reviewed();
        if (!item || item.group !== state.group) return null;
        const s = item.sizing, g = currentGroup();
        const c = state.cursors;
        const x0 = has(c.s_ref) ? c.s_ref : s.scan_start, x1 = has(c.s_meas) ? c.s_meas : s.scan_end;
        if (isRaster()) {
            const y0 = has(c.i_ref) ? c.i_ref : s.axial_start, y1 = has(c.i_meas) ? c.i_meas : s.axial_end;
            return { x0, x1, y0, y1 };
        }
        return { x0, x1, y0: Math.max(0, s.line_lo) - 0.5, y1: Math.min(g.shape[1] - 1, s.line_hi) + 0.5 };
    }
    const reviewed = () => (state.reviewing ? (state.indications || []).find(i => i.id === state.reviewing) : null);

    $('add-indication').addEventListener('click', addIndication);
    $('quick-indication').addEventListener('click', addIndication);

    /** The next (step 1) or previous (-1) indication in the list as shown, from the one reviewed (or along the scan from here). */
    function stepIndication(step) {
        const list = shownIndications();
        if (!list.length) return;
        const here = state.reviewing ? list.findIndex(i => i.id === state.reviewing)
            : list.findIndex(i => i.group === state.group && i.scan === state.scan && i.lateral === state.lateral);
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

    const sendable = () => (state.indications || []).filter(i => !$('send-accepted').checked || i.status === 'accepted');
    function renderSendIndications() {
        const list = sendable();
        const known = new Set(list.map(i => i.id));
        toReport.picked = new Set([...toReport.picked].filter(id => known.has(id)));
        if (!list.length) {
            $('send-indications').replaceChildren(note('None for this file yet.'));
            schedulePreview();
            return;
        }
        $('send-indications').replaceChildren(...list.map(item => {
            const label = Object.assign(document.createElement('label'), { className: 'analysis-pick' });
            const box = Object.assign(document.createElement('input'), { type: 'checkbox', checked: toReport.picked.has(item.id) });
            box.addEventListener('change', () => { if (box.checked) toReport.picked.add(item.id); else toReport.picked.delete(item.id); choiceChanged(); });
            const r = item.readings || {};
            const where = isRaster() ? format(item.index_position, 'value') : (item.angle === null ? '' : `${item.angle}°`);
            label.append(box, Object.assign(document.createElement('span'), { className: 'name',
                textContent: `#${item.number} · ${format(item.scan_position, 'value')}${where ? ' · ' + where : ''}${item.comment ? ' · ' + item.comment : ''}` }),
                Object.assign(document.createElement('span'), { className: 'meta', textContent: r['A%'] === undefined ? '' : `${r['A%'].toFixed(1)} %` }));
            return label;
        }));
        schedulePreview();
    }
    $('send-all').addEventListener('click', () => {
        const all = sendable().map(i => i.id);
        toReport.picked = toReport.picked.size === all.length ? new Set() : new Set(all);
        renderSendIndications();
        choiceChanged();
    });
    $('open-send').addEventListener('click', () => {
        if (!toReport.picked.size) toReport.picked = new Set(sendable().map(i => i.id));
        shell.open('report');
    });

    const pickedIndications = () => sendable().filter(i => toReport.picked.has(i.id));
    $('send-accepted').addEventListener('change', () => { renderSendIndications(); choiceChanged(); });
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
            box.replaceChildren(note(!toReport.report ? 'Pick a report.' : 'Pick indications.'));
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
        const here = { group: state.group, scan: state.scan, lateral: state.lateral, cursors: { ...state.cursors }, sizing: state.sizing,
                       gain: state.gain, review: state.gain !== state.buildGain, reviewing: state.reviewing, layout: grid.dataset.layout };
        // Every snip in the same four views: C-scan and B-scan over the S-scan and A-scan
        const snipLayout = here.layout !== 'A-B-C-S';
        if (snipLayout) {
            grid.dataset.layout = 'A-B-C-S';
            panels.refresh();
            await wait(50);
            panels.fit();
            scheduleProjections();
        }
        const out = [];
        try {
            for (const [n, item] of items.entries()) {
                $('send-result').textContent = `Taking the snips… ${n + 1} of ${items.length}`;
                await goTo(item);
                if (snipLayout && n === 0) await waitForViews();
                await wait(150);
                await loadReadings();
                await wait(350);   // the B-scan and the overlays follow the cursor
                zoomOn(item);
                out.push(composeImage().toDataURL('image/png'));
            }
        } finally {
            cview.view = null; cview.draw();
            bview.view = null; bview.draw();
            if (snipLayout) { grid.dataset.layout = here.layout; panels.refresh(); }
            if (here.group !== state.group) await setGroup(here.group, here.scan, here.lateral);
            state.sizing = here.sizing;
            state.reviewing = here.reviewing;
            setCursors(here.cursors);
            setGain(here.gain, here.review);
            await setScan(here.scan);
            setLateral(here.lateral, true);
            renderIndications();
        }
        return out;
    }

    /** Waits (a while at most) for the C-scan and B-scan to have their pictures after a layout change. */
    async function waitForViews() {
        for (let i = 0; i < 100 && !(cview.hasImage && bview.hasImage); i++) await wait(100);
    }

    /** The C-scan and B-scan zoomed in on an indication along the scan: its length and as much again each side (their full height). */
    function zoomOn(item) {
        const s = item.sizing || {};
        const start = s.scan_start ?? item.scan_position, end = s.scan_end ?? item.scan_position;
        if (!has(start) || !has(end)) return;
        const step = Math.abs(currentGroup().axes[0].resolution);
        const width = Math.max((end - start) * 3, step * 40);
        for (const view of [cview, bview]) {
            if (!view.hasImage) continue;
            const [, cy, , h] = view.fitView();
            view.view = [(start + end) / 2, cy, width, h];
            view.draw();
        }
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
            // Turned as on screen: about the stage's centre
            ctx.save();
            ctx.translate(stageBox.left - origin.left + stageBox.width / 2, stageBox.top - origin.top + title + stageBox.height / 2);
            ctx.rotate(ViewTurn.quarters(stage) * Math.PI / 2);
            for (const canvas of stage.querySelectorAll('canvas')) {
                ctx.drawImage(canvas, -stage.offsetWidth / 2, -stage.offsetHeight / 2, stage.offsetWidth, stage.offsetHeight);
            }
            ctx.restore();
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
        linking = true;   // each to its own fit, not to a linked view's
        try {
            sscan.view = null; sscan.draw();
            cview.view = null; cview.draw();
            bview.view = null; bview.draw();
            ascan.resetZoom();
        } finally { linking = false; }
    }

    // ── controls ──
    groupSelect.addEventListener('change', () => setGroup(+groupSelect.value, state.scan, state.lateral));
    // The scan box: a distance in the page's units, to the nearest scan line
    scanNumber.addEventListener('change', () => {
        const v = parseFloat(scanNumber.value);
        if (!state.info || !Number.isFinite(v)) { if (state.info) showScanPosition(); return; }
        setScan(Math.round((v * unitLength() - scanAxis().offset) / scanAxis().resolution));
    });
    scanNumber.addEventListener('keydown', e => { if (e.key === 'Enter') scanNumber.dispatchEvent(new Event('change')); });
    /** Scrolling over a top-bar value box steps it: up for more. */
    const onScroll = (box, step) => box.addEventListener('wheel', e => {
        e.preventDefault();
        const delta = e.deltaY || e.deltaX;   // Shift+wheel comes as deltaX
        if (delta && state.info) step(delta < 0 ? 1 : -1, e.shiftKey);
    }, { passive: false });
    onScroll(scanNumber.closest('.analysis-value-box'), (d, big) => setScan(state.scan + d * (big ? 10 : 1)));
    onScroll($('beam-box'), (d, big) => { setLateral(state.lateral + d * (big ? 10 : 1)); });
    onScroll(gainInput.closest('.analysis-value-box'), (d, fine) => setGain(state.gain + d * (fine ? 0.1 : 1)));
    // The selection box: a typed value (Enter), or scrolled over a step at a time (Shift: 10)
    const selectionInput = $('selection-value');
    const applySelection = () => {
        const v = parseFloat(selectionInput.value);
        if (selectionApply && Number.isFinite(v)) selectionApply(v);
        renderSelection();
    };
    selectionInput.addEventListener('change', applySelection);
    selectionInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); applySelection(); }
        if (e.key === 'Escape') { selectionInput.blur(); renderSelection(); }
    });
    selectionInput.addEventListener('blur', () => renderSelection());
    onScroll($('selection-readout'), (d, big) => {
        const sel = state.selected;
        if (!sel) return;
        // Steps scaled to the item's own view, as the wheel over that view would
        const view = sel.kind === 'cursor' ? { u: ascan, s: cview, i: sscan }[sel.key[0]] : sel.kind === 'gate' ? (sel.view === 'sscan' ? sscan : ascan) : null;
        nudge(d * (big ? 10 : 1), view);
    });
    $('beam-number').addEventListener('change', e => goToBeam(e.target.value));
    $('beam-number').addEventListener('keydown', e => { if (e.key === 'Enter') goToBeam(e.target.value); });
    $('beam-number').addEventListener('blur', showBeam);
    scanNumber.addEventListener('blur', () => { if (state.info) showScanPosition(); });
    gainInput.addEventListener('blur', () => { gainInput.value = state.gain.toFixed(1); });
    gainInput.addEventListener('keydown', e => { if (e.key === 'Enter') gainInput.dispatchEvent(new Event('change')); });
    $('scan-prev').addEventListener('click', () => setScan(state.scan - 1));
    $('scan-next').addEventListener('click', () => setScan(state.scan + 1));

    /**
     * The soft gain. review=true: only to look at an indication at its 80 % gain - the whole-file views
     * keep the gain they were built at (their shaders show the difference), so nothing is rebuilt.
     */
    function setGain(db, review = false) {
        state.gain = Math.round(Math.max(-40, Math.min(40, db)) * 10) / 10;
        gainInput.value = state.gain.toFixed(1);
        gainInput.classList.toggle('is-review', review);
        gainInput.title = review ? 'The indication at 80 % of full screen (its own gain); change it to set the soft gain' : 'Soft gain in dB';
        sscan.setGain(state.gain);
        ascan.setGain(state.gain);
        bview.setGain(state.gain);
        cview.setGain(state.gain - state.cscanGain);   // straight away; the rebuilt C-scan follows
        scheduleReadings();
        if (!review && Math.abs(state.gain - state.buildGain) > 1e-9) {
            state.buildGain = state.gain;
            scheduleProjections(800);
        }
        loadFrameGates(300);
    }
    gainInput.addEventListener('change', () => setGain(parseFloat(gainInput.value) || 0));

    /**
     * Auto 80%: the soft gain that brings the signal breaking gate A on the cursor's A-scan to 80% of
     * full screen. Worked out from the gate's peak with no soft gain (with gain the samples clip at
     * full scale, so a saturated peak can't say how far over it is).
     */
    async function auto80() {
        if (!state.info) return;
        const a = state.gateResults?.A;
        if (!a) { show('Auto 80% needs a gate A.'); return; }
        if (a.crossing_time === null || a.crossing_time === undefined) {
            show('Auto 80%: no signal breaks gate A on this A-scan - move the cursor onto the indication.');
            return;
        }
        const query = { path: state.path, group: state.group, scan: state.scan, lateral: state.lateral, gain: 0 };
        if (state.gatesEdited) query.gates = gatesParam();
        let data;
        try {
            data = await NdeClient.readings(urls, query);
        } catch (e) {
            show(e.message);
            return;
        }
        const peak = data.gates?.A?.amplitude;
        if (!(peak > 0)) { show('Auto 80%: gate A has no signal here.'); return; }
        show('');
        setGain(20 * Math.log10(80 / peak));
    }
    $('auto-80').addEventListener('click', auto80);
    refInput.addEventListener('change', () => {
        const v = parseFloat(refInput.value);
        state.refLevel = Number.isFinite(v) && v > 0 ? v : 80;
        refInput.value = state.refLevel;
        save();
        if (state.gates.some(isFloating)) { gatesChanged(); renderGates(); }   // their ratio is set against it
        renderReadings();
    });
    unitsSelect.addEventListener('change', () => {
        units = unitsSelect.value;
        localStorage.setItem('analysisUnits', units);
        sscan.drawOverlay();
        ascan.draw();
        if (state.info) {
            showDetails(); renderGates(); renderReadings(); setLateral(state.lateral, true); if (currentGroup()?.layout === 'beams' && (weld.shape || fileWeld())) showWeldEditor();
            showScanPosition();
            cview.drawOverlay(); bview.drawOverlay();
            if (state.cscan && state.cscan.mode !== 'amplitude') loadCscan(projectionRequest);
            renderIndications();
            fillFindGates();
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
            Escape: () => {
                if (!$('help-panel').hidden) toggleHelp(false);
                else if (state.selected) select(null);
                else shell.close();
            },
        };
        if (always[e.key]) { e.preventDefault(); always[e.key](); return; }
        if (!state.info) return;
        const big = e.shiftKey ? 10 : 1;
        const actions = {
            ArrowLeft: () => setScan(state.scan - big), ArrowRight: () => setScan(state.scan + big),
            PageUp: () => setScan(state.scan - 10), PageDown: () => setScan(state.scan + 10),
            ArrowUp: () => setLateral(state.lateral - 1), ArrowDown: () => setLateral(state.lateral + 1),
            '+': () => setGain(state.gain + 1), '=': () => setGain(state.gain + 1), '-': () => setGain(state.gain - 1),
            ...(e.shiftKey ? { Delete: clearAllCursors } : {}),
            a: auto80, A: auto80, t: toggleLegs, T: toggleLegs, l: sizeNow, L: sizeNow, n: addIndication, N: addIndication, g: nextGroup, G: nextGroup, p: saveImage, P: saveImage, f: fitAll, F: fitAll, ']': () => stepIndication(1), '[': () => stepIndication(-1),
            ...(state.reviewing ? { Enter: () => review('accepted'), x: () => review('rejected'), X: () => review('rejected'),
                                    6: () => resize('6'), 1: () => resize('12'), 2: () => resize('20'), s: keepCursors, S: keepCursors } : {}),
        };
        if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
    });

    function applyPalettes() {
        sscan.setPalette(ampPalette.value);
        bview.setPalettes({ amplitude: ampPalette.value });
        cview.setPalettes({ amplitude: ampPalette.value, range: rangePalette.value });
        renderPaletteBar();   // its track shows this palette
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
