// Probe / wedge catalogue selects (select[data-catalogue="probe"|"wedge"], set up by
// reports/forms.py::catalogue_choices) on any page: the scan plan, setups, the NDE import and the
// report editor's setup blocks, including blocks added later.
//  - Picking a probe reloads the wedge list with the wedges that fit it.
//  - Type-to-filter boxes above both lists ('5L16A1' finds 5L16-A1; one match is picked).
// Pages use window.CatalogueSelect.setPair(probeSelect, probePk, wedgePk) to fill both.

(function () {
    function wedgeFor(probeSelect) {
        // The wedge select that belongs with this probe select (same setup block / form)
        let node = probeSelect.parentElement;
        while (node) {
            const wedge = node.querySelector('select[data-catalogue="wedge"]');
            if (wedge) return wedge;
            node = node.parentElement;
        }
        return null;
    }

    async function loadWedges(probeSelect) {
        const wedgeSelect = wedgeFor(probeSelect);
        if (!wedgeSelect || !probeSelect.value) return wedgeSelect;  // without a probe the general wedges stay
        const response = await fetch(`${wedgeSelect.dataset.wedgesUrl}?probe=${encodeURIComponent(probeSelect.value)}`);
        if (!response.ok) return wedgeSelect;
        const { wedges } = await response.json();
        const current = wedgeSelect.value;
        const blank = wedgeSelect.options[0];
        wedgeSelect.replaceChildren(blank, ...wedges.map(([pk, name]) => new Option(name, pk)));
        wedgeSelect.value = wedges.some(([pk]) => String(pk) === current) ? current : '';
        if (wedgeSelect.value !== current) {
            wedgeSelect.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return wedgeSelect;
    }

    async function setPair(probeSelect, probePk, wedgePk) {
        probeSelect.value = probePk ?? '';
        const wedgeSelect = await loadWedges(probeSelect);
        if (wedgeSelect && wedgePk != null) {
            if (![...wedgeSelect.options].some(o => o.value === String(wedgePk))) return;
            wedgeSelect.value = String(wedgePk);
            wedgeSelect.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    document.addEventListener('change', event => {
        if (event.target.matches('select[data-catalogue="probe"]')) {
            loadWedges(event.target);
        }
    });

    // ── Type-to-filter boxes ─────────────────────────────────────────────

    function simplify(text) {
        return text.toLowerCase().replace(/[^a-z0-9.]/g, '');
    }

    function addFilter(select) {
        if (select.dataset.filterAdded) return;
        select.dataset.filterAdded = '1';
        const placeholder = select.dataset.catalogue === 'probe'
            ? 'Type to filter probes, e.g. 5L16A1' : 'Type to filter wedges, e.g. N60S';
        const box = document.createElement('input');
        box.type = 'search';
        box.className = 'form-control form-control-sm mb-1 select-filter';
        box.placeholder = placeholder;
        box.setAttribute('aria-label', placeholder);
        select.before(box);

        const apply = () => {
            const query = simplify(box.value);
            const visible = [];
            for (const option of select.options) {
                if (!option.value) continue;
                option.hidden = Boolean(query) && !simplify(option.text).includes(query);
                if (!option.hidden) visible.push(option);
            }
            if (query && visible.length === 1 && select.value !== visible[0].value) {
                select.value = visible[0].value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };
        box.addEventListener('input', apply);
        new MutationObserver(apply).observe(select, { childList: true });  // the wedge list is rebuilt
        // Typing in a filter box is not a change to the form itself (no unsaved-changes / redraw)
        box.addEventListener('input', event => event.stopPropagation());
    }

    function wire(root) {
        root.querySelectorAll('select[data-catalogue]').forEach(addFilter);
    }

    wire(document);
    // Setup blocks added in the report editor
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === 1) wire(node);
    }))).observe(document.body, { childList: true, subtree: true });

    window.CatalogueSelect = { loadWedges, setPair };
})();
