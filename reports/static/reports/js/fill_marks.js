// Fill marks for the report editor, like the weld form's conditional formatting: an empty field
// only the technician can fill is outlined red, an empty field an .nde import, the scope library
// or the sensitivity block usually fills is outlined yellow (data-fill="user" / "auto", set by
// reports/fill_marks.py). On while the report type has fill_marks (create_report.js adds the
// form's fill-marks class); N/A and hidden fields aren't marked. Other editors opt in with a
// form marked data-fill-marks (the scan plan editor); there, fields not on screen (another mode's
// or weld type's) aren't marked either.

(function () {
    const form = document.getElementById('report-form') || document.querySelector('form[data-fill-marks]');
    if (!form) return;
    const visibleOnly = form.hasAttribute('data-fill-marks');
    const counts = { user: document.getElementById('fill-count-user'), auto: document.getElementById('fill-count-auto') };

    function refresh() {
        const missing = { user: 0, auto: 0 };
        form.querySelectorAll('[data-fill]').forEach(el => {
            const skipped = el.readOnly || el.disabled || el.type === 'hidden' || el.closest('[hidden], template')
                || (visibleOnly && !el.getClientRects().length);
            const empty = !skipped && el.type !== 'checkbox' && !String(el.value ?? '').trim();
            el.classList.toggle('fill-missing', empty);
            if (empty) missing[el.dataset.fill] += 1;
        });
        // Only when it changes: the counts are in the form, whose changes trigger this again
        for (const kind of ['user', 'auto']) {
            if (counts[kind] && counts[kind].textContent !== String(missing[kind])) counts[kind].textContent = missing[kind];
        }
        sectionBadges();
    }

    // What's left per section, beside its name in the section menu
    function sectionBadges() {
        const on = form.classList.contains('fill-marks');
        document.querySelectorAll('[data-nav-section]').forEach(link => {
            const section = form.querySelector(`.editor-section[data-section="${link.dataset.navSection}"]`);
            const left = on && section ? section.querySelectorAll('.fill-missing').length : 0;
            let badge = link.querySelector('.nav-missing');
            if (!left) {
                badge?.remove();
                return;
            }
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'nav-missing';
                badge.title = 'Fields still to fill in this section';
                link.append(badge);
            }
            if (badge.textContent !== String(left)) badge.textContent = left;
        });
    }

    // "Next missing": the next outlined field after the last one you were in (clicking the button
    // takes the focus, so remember the field), from the top at the end
    let lastField = null;
    form.addEventListener('focusin', event => {
        if (event.target.matches('input, select, textarea')) lastField = event.target;
    });
    document.getElementById('fill-next')?.addEventListener('click', () => {
        const missing = Array.from(form.querySelectorAll('.fill-missing'));
        if (!missing.length) return;
        const here = lastField;
        const next = missing.find(el => here && here !== el
            && (here.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) || missing[0];
        next.focus();
        next.scrollIntoView({ block: 'center' });
    });

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
    // How many fields are still to fill in part of the form (now, not on the next frame)
    function missingIn(el) {
        refresh();
        return el.querySelectorAll('.fill-missing').length;
    }
    window.FillMarks = { refresh: schedule, missingIn };
    refresh();
})();
