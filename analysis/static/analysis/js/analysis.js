// The Analysis page: pick an .nde file from the working folders and a group, step through its scan
// lines, and look at each one's S-scan (true geometry) and the A-scan under the beam cursor with
// OmniPC's gate readings. Scan lines are stepped by number for now (encoder positions come later).
//
// Keys: Left / Right a scan line (Shift: 10), PageUp / PageDown 10 lines, Up / Down the beam
// cursor, + / - soft gain by 1 dB. The state is kept in the URL so a reload comes back to it.

(function () {
    const page = document.getElementById('analysis');
    if (!page) return;
    const urls = { files: page.dataset.filesUrl, file: page.dataset.fileUrl, frame: page.dataset.frameUrl,
                   readings: page.dataset.readingsUrl };
    const $ = id => document.getElementById(id);
    const fileSelect = $('file-select'), fileFilter = $('file-filter'), groupSelect = $('group-select');
    const slider = $('scan-slider'), scanNumber = $('scan-number'), gainInput = $('gain');
    const unitsSelect = $('units'), axisSelect = $('axis');
    const status = $('analysis-status');

    const READING_NAMES = {
        'A%': 'Peak amplitude in gate A', 'SA^': 'Sound path to the gate A peak', 'DA^': 'Depth of the gate A peak',
        'PA^': 'Gate A peak from the probe', 'ViA^': 'Index position of the gate A peak',
        'B%': 'Peak amplitude in gate B', 'SB^': 'Sound path to the gate B peak', 'DB^': 'Depth of the gate B peak',
        'A/-I/': 'Gate A crossing from the interface (gate I crossing)', 'T(B/-A/)': 'Thickness: gate A crossing to gate B crossing',
    };

    const state = { path: '', group: 0, scan: 0, lateral: 0, gain: 0, info: null, frame: null, values: null };
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
        onHover: (x, y) => { $('sscan-readout').textContent = x === null ? '' : `Index ${format(x)} · depth ${format(y)}`; },
    });
    const ascan = new AScanView($('ascan-stage'), {
        format, unitLength,
        onHover: text => { $('ascan-readout').textContent = text || ''; },
    });

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
        const s = state.info.specimen || {};
        $('file-details').textContent = [
            `NDE ${state.info.version}`, s.thickness ? `part ${format(s.thickness)} thick` : '',
            s.material || '', state.info.scan_pattern || '',
        ].filter(Boolean).join(' · ');
        show('');
        await setGroup(chosen.id, scan, lateral);
    }

    async function setGroup(id, scan = 0, lateral = 0) {
        state.group = id;
        const g = currentGroup();
        const samples = g.shape[2];
        sscan.setGeometry(g.rays, samples, state.info.specimen?.thickness);
        $('true-geometry').checked = sscan.trueGeometry;
        slider.max = scanNumber.max = g.shape[0] - 1;
        $('scan-count').textContent = `of ${g.shape[0]}`;
        state.lateral = Math.min(lateral, g.shape[1] - 1);
        await setScan(Math.min(scan, g.shape[0] - 1));
    }

    const currentGroup = () => state.info.groups.find(g => g.id === state.group);

    // ── scan line, beam cursor, readings ──
    let frameRequest = 0;
    async function setScan(scan) {
        const g = currentGroup();
        if (!g) return;
        state.scan = Math.max(0, Math.min(g.shape[0] - 1, scan));
        slider.value = scanNumber.value = state.scan;
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
        setLateral(state.lateral, true);
        remember();
        // Read the neighbouring lines ahead so stepping stays smooth
        for (const next of [state.scan + 1, state.scan - 1]) {
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
                    period: g.axes[2].resolution, gates: null });
        const beam = g.beams[lateral];
        $('ascan-label').textContent = g.layout === 'beams'
            ? `Beam ${lateral + 1} of ${g.shape[1]} · ${beam.refracted_angle}°`
            : `Index line ${lateral + 1} of ${g.shape[1]} · ${format(beam.v_offset)}`;
        $('sscan-label').textContent = `Scan line ${state.scan + 1}`;
        remember();
        scheduleReadings();
    }

    let readingsTimer = null, readingsRequest = 0;
    function scheduleReadings() {
        clearTimeout(readingsTimer);
        readingsTimer = setTimeout(loadReadings, 60);
    }

    async function loadReadings() {
        const mine = ++readingsRequest;
        let data;
        try {
            data = await NdeClient.readings(urls, { path: state.path, group: state.group, scan: state.scan,
                                                    lateral: state.lateral, gain: state.gain });
        } catch (e) {
            show(e.message);
            return;
        }
        if (mine !== readingsRequest) return;
        ascan.set({ gates: data.gates });
        const list = $('readings');
        const rows = Object.entries(data.readings).map(([name, value]) => {
            const dt = Object.assign(document.createElement('dt'), { textContent: name, title: READING_NAMES[name] || '' });
            const dd = Object.assign(document.createElement('dd'), {
                className: 'mono', textContent: name.includes('%') ? `${value.toFixed(1)} %` : format(value),
            });
            return [dt, dd];
        }).flat();
        list.replaceChildren(...(rows.length ? rows : [Object.assign(document.createElement('dd'), {
            className: 'text-muted-cell', textContent: 'No gate signal on this line.' })]));
    }

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
        scheduleReadings();
    }
    gainInput.addEventListener('change', () => setGain(parseFloat(gainInput.value) || 0));
    $('gain-down').addEventListener('click', () => setGain(state.gain - 1));
    $('gain-up').addEventListener('click', () => setGain(state.gain + 1));
    unitsSelect.addEventListener('change', () => {
        units = unitsSelect.value;
        localStorage.setItem('analysisUnits', units);
        sscan.drawOverlay();
        ascan.draw();
        if (state.info) { setLateral(state.lateral, true); openDetails(); }
    });
    const openDetails = () => {
        const s = state.info?.specimen || {};
        $('file-details').textContent = [`NDE ${state.info.version}`, s.thickness ? `part ${format(s.thickness)} thick` : '',
                                         s.material || '', state.info.scan_pattern || ''].filter(Boolean).join(' · ');
    };
    axisSelect.addEventListener('change', () => ascan.setAxis(axisSelect.value));
    $('sscan-fit').addEventListener('click', () => { sscan.view = null; sscan.draw(); });
    $('true-geometry').addEventListener('change', e => sscan.setTrueGeometry(e.target.checked));

    document.addEventListener('keydown', e => {
        if (!state.info || e.target.closest('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
        const big = e.shiftKey ? 10 : 1;
        const actions = {
            ArrowLeft: () => setScan(state.scan - big), ArrowRight: () => setScan(state.scan + big),
            PageUp: () => setScan(state.scan - 10), PageDown: () => setScan(state.scan + 10),
            ArrowUp: () => setLateral(state.lateral - 1), ArrowDown: () => setLateral(state.lateral + 1),
            '+': () => setGain(state.gain + 1), '=': () => setGain(state.gain + 1), '-': () => setGain(state.gain - 1),
        };
        if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
    });

    loadFiles().catch(e => show(e.message));
})();
