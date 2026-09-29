// NDE import page: drag-and-drop upload, and filling the setup form from the parsed file.

// ── Upload ───────────────────────────────────────────────────────────────

const uploadForm = document.getElementById('nde-upload-form');
const fileInput = document.getElementById('nde_file');
const dropZone = document.getElementById('drop-zone');

function submitFile() {
    const file = fileInput.files[0];
    if (!file) return;
    dropZone.classList.add('busy');
    document.getElementById('drop-hint').textContent = `Reading ${file.name}…`;
    uploadForm.submit();
}

fileInput.addEventListener('change', submitFile);

['dragenter', 'dragover'].forEach(type => dropZone.addEventListener(type, e => {
    e.preventDefault();
    dropZone.classList.add('dragging');
}));

['dragleave', 'drop'].forEach(type => dropZone.addEventListener(type, () => dropZone.classList.remove('dragging')));

dropZone.addEventListener('drop', e => {
    e.preventDefault();
    if (!e.dataTransfer.files.length) return;
    fileInput.files = e.dataTransfer.files;
    submitFile();
});

// ── Populate the setup form from the file ────────────────────────────────

const dataEl = document.getElementById('nde-setup-data');
const NDE_DATA = dataEl ? JSON.parse(dataEl.textContent) : null;

// Raw metric values stored once on populate so toggling can reconvert without re-parsing
let _rawDiameter = null, _rawXRes = null, _rawYRes = null, _rawFocDepth = null;
let _rawOD = null, _rawThickness = null, _rawScanQty = 0, _beams = null, _rawVelocity = null;
let unitIsImperial = true;

function safeGet(obj, ...keys) {
    return keys.reduce((acc, key) => acc != null ? acc[key] : undefined, obj);
}

// Convert meters to inches (imperial) or mm (metric)
function dist(meters, impDec = 3, metDec = 2) {
    if (meters == null) return undefined;
    return unitIsImperial
        ? (meters * 39.3701).toFixed(impDec)
        : (meters * 1000).toFixed(metDec);
}

// Convert m/s to in/μs (imperial) or keep as m/s (metric)
function vel(mps) {
    if (mps == null) return undefined;
    return unitIsImperial
        ? (mps / 25400).toFixed(4)
        : mps.toFixed(0);
}

function setValues(mappings) {
    for (const [id, value] of Object.entries(mappings)) {
        if (value != null) {
            const el = document.getElementById(id);
            if (el) el.value = value;
        }
    }
}

function applyUnits() {
    const yResStr = dist(_rawYRes, 4, 3);
    const scanLenRaw = (_rawXRes != null && _rawScanQty) ? _rawXRes * _rawScanQty : null;
    const scanWidthStr = (_beams && yResStr)
        ? (_beams.length * parseFloat(yResStr)).toFixed(3)
        : undefined;

    setValues({
        'id_probe_diameter':     dist(_rawDiameter, 4, 3),
        'id_foc_depth':          dist(_rawFocDepth, 3, 2),
        'id_x_res':              dist(_rawXRes, 4, 3),
        'id_y_res':              yResStr,
        'id_scan_length':        dist(scanLenRaw, 3, 2),
        'id_scan_width':         scanWidthStr,
        'id_specimen_od':        _rawOD != null ? dist(_rawOD * 2, 3, 2) : undefined,
        'id_specimen_thickness': dist(_rawThickness, 4, 3),
        'id_sound_velocity':     vel(_rawVelocity),
    });
}

function setUnit(imperial) {
    unitIsImperial = imperial;
    document.getElementById('btn-imperial').className = `btn ${imperial ? 'btn-primary' : 'btn-outline-primary'}`;
    document.getElementById('btn-metric').className = `btn ${imperial ? 'btn-outline-primary' : 'btn-primary'}`;
    applyUnits();
}

function populateFields(d) {
    const probe = safeGet(d, 'probes', 0) || {};
    const isPA = !!probe.phasedArrayLinear;
    const probeData = isPA ? probe.phasedArrayLinear : probe.conventionalRound;

    _rawDiameter  = !isPA ? safeGet(probeData, 'diameter') : null;
    _rawXRes      = safeGet(d, 'groups', 0, 'datasets', 0, 'dimensions', 0, 'resolution');
    _rawYRes      = safeGet(d, 'groups', 0, 'datasets', 0, 'dimensions', 1, 'resolution');
    _rawFocDepth  = safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'focusing', 'distance');
    _rawOD        = safeGet(d, 'specimens', 0, 'pipeGeometry', 'outerRadius');
    _rawThickness = safeGet(d, 'specimens', 0, 'pipeGeometry', 'thickness');
    _rawScanQty   = safeGet(d, 'groups', 0, 'datasets', 0, 'dimensions', 0, 'quantity') ?? 0;
    _beams        = safeGet(d, 'groups', 0, 'datasets', 0, 'dimensions', 1, 'beams');
    _rawVelocity  = safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'velocity');

    let angleStep, angleRange;
    if (_beams && _beams.length >= 2) {
        const step = _beams[1].refractedAngle - _beams[0].refractedAngle;
        angleStep = step.toFixed(1) + '°';
        angleRange = `${_beams[0].refractedAngle}°-${_beams[_beams.length - 1].refractedAngle}°`;
    }

    // Unit-independent fields
    const rawFreq = safeGet(probeData, 'centralFrequency');
    setValues({
        'id_scope_platform':    safeGet(d, 'acquisitionUnits', 0, 'platform'),
        'id_scope_model':       safeGet(d, 'acquisitionUnits', 0, 'model'),
        'id_scope_serial':      safeGet(d, 'acquisitionUnits', 0, 'serialNumber'),
        'id_transducer_model':  safeGet(d, 'probes', 0, 'model'),
        'id_transducer_serial': safeGet(d, 'probes', 0, 'serialNumber'),
        'id_wedge_model':       safeGet(d, 'wedges', 0, 'model'),
        'id_wedge_angle':       safeGet(d, 'wedges', 0, 'angleBeamWedge', 'mountingLocations', 0, 'wedgeAngle'),
        'id_freq':              rawFreq != null ? (rawFreq / 1_000_000) + 'MHz' : undefined,
        'id_elements':          isPA ? safeGet(probeData, 'primaryAxis', 'elementQuantity') : '1',
        'id_wave_propagation':  safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'waveMode'),
        'id_gain':              safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'gain'),
        'id_ref_gain':          safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'referenceGain'),
        'id_voltage':           safeGet(d, 'groups', 0, 'processes', 0, 'ultrasonicPhasedArray', 'pulse', 'voltage'),
        'id_cal_material':      safeGet(d, 'specimens', 0, 'pipeGeometry', 'material', 'name'),
        'id_angle_step':        angleStep,
        'id_angle_range':       angleRange,
    });

    applyUnits();
}

if (NDE_DATA) {
    document.querySelectorAll('[data-unit]').forEach(button => {
        button.addEventListener('click', () => setUnit(button.dataset.unit === 'imperial'));
    });
    populateFields(NDE_DATA);
}
