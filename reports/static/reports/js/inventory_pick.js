// Serial number pickers (components/inventory_pickers.html, equipment/pickers.py): a serial field
// lists the inventory's serials; picking one (or typing one the inventory has) fills the fields
// beside it with what the inventory knows: a setup's scope, probe and cal block; the weld form's
// instrument card, probe columns and additional blocks.

(function () {
    const script = document.getElementById('inventory-picks');
    if (!script) return;
    const picks = JSON.parse(script.textContent);

    // [field name pattern (group 1: the prefix the filled fields share), datalist, inventory, part]
    const RULES = [
        [/^((?:setups-\d+-)?)scope_serial$/, 'inv-scopes', 'scopes', 'setup'],
        [/^()inst_serial$/, 'inv-scopes', 'scopes', 'weld'],
        [/^((?:setups-\d+-)?)transducer_serial$/, 'inv-probes', 'probes', 'setup'],
        [/^(probes-\d+-)serial$/, 'inv-probes', 'probes', 'column'],
        [/^((?:setups-\d+-)?)cal_block_serial$/, 'inv-blocks', 'blocks', 'setup'],
        [/^(add[12]_)serial$/, 'inv-blocks', 'blocks', 'weld'],
    ];

    function ruleFor(input) {
        if (!(input instanceof HTMLInputElement) || !input.name) return null;
        for (const [pattern, list, source, part] of RULES) {
            const match = input.name.match(pattern);
            if (match) return { prefix: match[1], list, source, part };
        }
        return null;
    }

    function attach(input) {
        const rule = ruleFor(input);
        if (rule && !input.hasAttribute('list') && Object.keys(picks[rule.source]).length) {
            input.setAttribute('list', rule.list);
            input.autocomplete = 'off';
        }
        return rule;
    }

    // Fields added later (a new setup block, a weld column) get their list on first focus
    document.querySelectorAll('input').forEach(attach);
    document.addEventListener('focusin', e => attach(e.target));

    function fill(input) {
        const rule = ruleFor(input);
        if (!rule || input.disabled || input.readOnly) return;
        const item = picks[rule.source][input.value.trim().toUpperCase()];
        if (!item || !item[rule.part]) return;
        // By name, not form.elements: a saved setup's "elements" field hides form.elements
        const scope = input.form || document;
        for (const [name, value] of Object.entries(item[rule.part])) {
            const target = scope.querySelector(`[name="${rule.prefix}${name}"]`);
            if (!target || target === input || target.type === 'hidden' || target.value === String(value)) continue;
            target.value = value;
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    // A pick from the list (or pasted), and a serial typed in full once the field is left
    document.addEventListener('input', e => {
        if (!e.inputType || e.inputType === 'insertReplacementText' || e.inputType === 'insertFromPaste') fill(e.target);
    });
    document.addEventListener('change', e => { if (e.isTrusted) fill(e.target); });
})();
