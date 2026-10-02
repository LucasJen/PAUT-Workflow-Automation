// The weld form's Sensitivity block & test material card (reports/editor/_materials_card.html):
// picking a library block fills the card (and the instrument's encoder fields still blank),
// Auto-detect picks the block for the scanned part, and the TCG distances follow T.

(function () {
    const card = document.getElementById('materials-card');
    if (!card) return;
    const form = card.closest('form');
    const blocks = JSON.parse(document.getElementById('sensitivity-blocks').textContent);
    const picker = form.elements.sensitivity_block;
    const status = document.getElementById('materials-status');
    const thickness = form.elements.tcg_thickness;

    function showStatus(text, isError = false) {
        status.textContent = text;
        status.classList.toggle('text-danger', isError);
    }

    function fillCard(values) {
        for (const [name, value] of Object.entries(values)) {
            const input = form.elements[name];
            if (input && name !== 'sensitivity_block') input.value = value ?? '';
        }
        distances();
    }

    // The block's encoder, resolution and speed go to the instrument only where it's blank
    function fillEncoder(values) {
        for (const [name, value] of Object.entries(values || {})) {
            const input = form.elements[name];
            if (input && !input.value.trim()) input.value = value;
        }
    }

    // TCG points at 1T, 2T and 3T of the block thickness, each with the reflector and amplitude
    function distances() {
        const t = parseFloat((thickness.value.match(/-?\d+(\.\d+)?/) || [''])[0]);
        card.querySelectorAll('.tcg-distance').forEach(cell => {
            cell.textContent = Number.isFinite(t) ? (t * Number(cell.dataset.multiple)).toFixed(3) : '';
        });
        card.querySelectorAll('.tcg-echo').forEach(cell => {
            cell.textContent = form.elements[cell.dataset.echo]?.value || '';
        });
    }

    picker.addEventListener('change', () => {
        const block = blocks[picker.value];
        if (!block) return;
        fillCard(block.card);
        fillEncoder(block.encoder);
        showStatus('');
    });
    for (const name of ['tcg_thickness', 'tcg_reflector', 'tcg_amplitude']) {
        form.elements[name]?.addEventListener('input', distances);
    }

    const detect = document.getElementById('materials-detect');
    async function autoDetect() {
        const body = new FormData();
        body.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
        body.append('scan_part', form.elements.scan_part?.value || '');
        body.append('pipe_size', form.elements.pipe_size?.value || '');   // for plate specimens
        showStatus('Looking for the block…');
        try {
            const response = await fetch(card.dataset.detectUrl, { method: 'POST', body });
            const data = await response.json();
            fillCard(data.values || {});
            if (data.ok) {
                picker.value = String(data.values.sensitivity_block);
                fillEncoder(data.encoder);
            }
            showStatus(data.message, !data.ok);
            form.dispatchEvent(new Event('input', { bubbles: true }));
        } catch (error) {
            showStatus("Couldn't reach the block library.", true);
        }
    }
    detect?.addEventListener('click', autoDetect);
    // An .nde import runs it when no block is picked yet (weld_grid.js)
    window.Materials = { autoDetectIfEmpty: () => (detect && !picker.value ? autoDetect() : null) };

    distances();
})();
