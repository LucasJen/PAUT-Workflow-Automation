// Fill marks for the weld report editor, like the form's conditional formatting: an empty field
// only the technician can fill is outlined red, an empty field an .nde import, the scope library
// or the sensitivity block usually fills is outlined yellow (data-fill="user" / "auto", set by
// reports/weld_form.py). On while the report type has fill_marks (create_report.js adds the
// form's fill-marks class); N/A and hidden fields aren't marked.

(function () {
    const form = document.getElementById('report-form');
    if (!form) return;
    const counts = { user: document.getElementById('fill-count-user'), auto: document.getElementById('fill-count-auto') };

    function refresh() {
        const missing = { user: 0, auto: 0 };
        form.querySelectorAll('[data-fill]').forEach(el => {
            const skipped = el.readOnly || el.disabled || el.type === 'hidden' || el.closest('[hidden], template');
            const empty = !skipped && el.type !== 'checkbox' && !String(el.value ?? '').trim();
            el.classList.toggle('fill-missing', empty);
            if (empty) missing[el.dataset.fill] += 1;
        });
        // Only when it changes: the counts are in the form, whose changes trigger this again
        for (const kind of ['user', 'auto']) {
            if (counts[kind] && counts[kind].textContent !== String(missing[kind])) counts[kind].textContent = missing[kind];
        }
    }

    // Values also change without events (imports, Auto-detect, added columns and welds), so check
    // again after anything happens in the form, once per frame
    let pending = false;
    function schedule() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; refresh(); });
    }
    ['input', 'change', 'click'].forEach(type => form.addEventListener(type, () => setTimeout(schedule)));
    new MutationObserver(schedule).observe(form, { childList: true, subtree: true });
    window.FillMarks = { refresh: schedule };
    refresh();
})();
