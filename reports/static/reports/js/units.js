// Units selects (select[data-unit-toggle], see reports/forms.py::unit_toggle): changing between
// imperial and metric converts the measured values in the same setup block / form.
// data-unit-toggle lists the fields by kind:
//   length      in <-> mm         ('0.280' <-> '7.11', '11.811 × 11.811 in' <-> '300.00 × 300.00 mm')
//   velocity    in/µs <-> m/s     ('0.1276' <-> '3241')
//   per_length  steps/in <-> steps/mm
// Pages that set a Units select from code call window.Units.sync(select) afterwards.

(function () {
    const MM_PER_IN = 25.4;
    const NUMBER = /-?\d+(?:\.\d+)?/g;

    function format(value, kind, to) {
        if (kind === 'velocity') return to === 'metric' ? value.toFixed(0) : value.toFixed(4);
        if (kind === 'per_length') return value.toFixed(Math.abs(value) < 1 ? 4 : 2);
        if (to === 'metric') return value.toFixed(2);
        return value.toFixed(Math.abs(value) < 0.1 ? 4 : 3);
    }

    function factor(kind, to) {
        const toMetric = to === 'metric';
        if (kind === 'velocity') return toMetric ? MM_PER_IN * 1000 : 1 / (MM_PER_IN * 1000);
        if (kind === 'per_length') return toMetric ? 1 / MM_PER_IN : MM_PER_IN;
        return toMetric ? MM_PER_IN : 1 / MM_PER_IN;
    }

    function convertText(text, kind, to) {
        if (!text || !text.trim()) return text;
        const f = factor(kind, to);
        let out = text.replace(NUMBER, n => format(parseFloat(n) * f, kind, to));
        if (to === 'metric') {
            out = out.replace(/\bin\b\.?/g, 'mm').replace(/(\S)\s*"/g, '$1 mm');
        } else {
            out = out.replace(/\bmm\b/g, 'in');
        }
        return out;
    }

    function scopeOf(select) {
        return select.closest('.setup-block') || select.form || document;
    }

    function fieldsIn(scope, name) {
        return scope.querySelectorAll(`[name="${name}"], [name$="-${name}"]`);
    }

    function convert(select, from, to) {
        if (from === to) return;
        const groups = JSON.parse(select.dataset.unitToggle || '{}');
        const scope = scopeOf(select);
        for (const [kind, names] of Object.entries(groups)) {
            for (const name of names) {
                fieldsIn(scope, name).forEach(input => { input.value = convertText(input.value, kind, to); });
            }
        }
    }

    function sync(select) {
        select.dataset.units = select.value;
    }

    document.addEventListener('change', event => {
        const select = event.target;
        if (!select.matches('select[data-unit-toggle]')) return;
        convert(select, select.dataset.units || (select.value === 'metric' ? 'imperial' : 'metric'), select.value);
        sync(select);
        select.form?.dispatchEvent(new Event('input', { bubbles: true }));  // redraws / unsaved-changes
    });

    function syncAll(root) {
        root.querySelectorAll('select[data-unit-toggle]').forEach(sync);
    }
    syncAll(document);
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === 1) syncAll(node);
    }))).observe(document.body, { childList: true, subtree: true });

    window.Units = { sync, convertText, MM_PER_IN };
})();
