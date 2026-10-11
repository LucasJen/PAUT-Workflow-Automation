// A setup block's Weld & offsets panel: the weld (bevel angle, root face, root gap, cap width) and the
// probe's offsets - wedge front to the weld centre line - for the setup picture's scan plan, which
// draws the weld at each offset, one drawing per offset side by side (setup_sheet.py). The first
// offset is the setup's index_offset field; the others are kept comma separated in extra_offsets.

(function () {
    const el = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };
    const unitsOf = block => (block.querySelector('select[name$="-units"]')?.value === 'metric' ? 'mm' : 'in');

    function init(block) {
        const panel = block.querySelector('[data-setup-weld]');
        if (!panel || panel.dataset.ready) return;
        panel.dataset.ready = '1';
        panel.querySelector('[data-add-offset]').addEventListener('click', () => { addOffset(block, ''); write(block); });
        panel.querySelector('input[name$="-weld_on"]')?.addEventListener('change', () => showOn(block));
        panel.querySelector('[data-weld-preview]')?.addEventListener('click', () => window.SetupValues?.preview(block));
        render(block);
    }

    const list = block => block.querySelector('[data-offset-list]');
    const extraInput = block => block.querySelector('input[name$="-extra_offsets"]');

    function addOffset(block, value) {
        const input = el('input', { type: 'text', className: 'form-control form-control-sm mono setup-weld-extra', value, inputMode: 'decimal' });
        input.setAttribute('aria-label', 'Another offset');
        input.addEventListener('change', () => write(block));
        const remove = el('button', { type: 'button', className: 'btn btn-sm btn-link setup-weld-remove', title: 'Remove this offset', innerHTML: '<i class="bi bi-x-lg"></i>' });
        remove.addEventListener('click', () => { wrap.remove(); write(block); });
        const wrap = el('span', { className: 'setup-weld-extra-wrap' }, input, remove);
        list(block).append(wrap);
        return input;
    }

    /** The further offsets back into the hidden field, comma separated. */
    function write(block) {
        const values = [...block.querySelectorAll('.setup-weld-extra')].map(i => i.value.trim()).filter(Boolean);
        const hidden = extraInput(block);
        hidden.value = values.join(', ');
        hidden.dispatchEvent(new Event('input', { bubbles: true }));
        relabel(block);
    }

    function relabel(block) {
        const first = block.querySelector('input[name$="-index_offset"]');
        if (first) first.title = 'Offset 1: wedge front to the weld centre line';
        block.querySelectorAll('.setup-weld-extra').forEach((input, i) => { input.title = `Offset ${i + 2}`; });
        block.querySelector('[data-offset-unit]').textContent = unitsOf(block);
    }

    function render(block) {
        list(block).querySelectorAll('.setup-weld-extra-wrap').forEach(w => w.remove());
        for (const value of (extraInput(block)?.value || '').split(',').map(v => v.trim()).filter(Boolean)) addOffset(block, value);
        relabel(block);
        showOn(block);
    }

    /** The weld's fields are kept either way; off, the panel is dimmed and the scan plan has no weld. */
    function showOn(block) {
        const on = block.querySelector('input[name$="-weld_on"]')?.checked;
        const panel = block.querySelector('[data-setup-weld]');
        panel.classList.toggle('is-off', !on);
        // The picture is drawn from the setup's .nde: no file, nothing to preview
        const preview = panel.querySelector('[data-weld-preview]');
        if (preview) preview.hidden = !block.querySelector('input[name$="-nde_sheet"]')?.value.trim();
    }

    document.querySelectorAll('.setup-block').forEach(init);
    document.addEventListener('setup-filled', e => {
        const block = e.target.closest('.setup-block');
        if (block) { init(block); render(block); }
    });
    // The units changed: the hidden list was converted with the other lengths - show it again
    document.addEventListener('change', e => {
        if (!e.target.matches?.('select[name$="-units"]')) return;
        const block = e.target.closest('.setup-block');
        if (block) setTimeout(() => render(block), 0);
    });
    new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(node => {
        if (node.nodeType === 1 && node.matches?.('.setup-block')) init(node);
    }))).observe(document.getElementById('setup-formset-container') || document.body, { childList: true });
})();
