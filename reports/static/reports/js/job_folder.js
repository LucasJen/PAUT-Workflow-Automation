// Guided Creation, step 1 (start_from_files.html): the job folder modes (existing / new / files
// only), what the report starts from (the .nde files or an existing weld report / Short Form) and the
// folder list's search.

(function () {
    const form = document.getElementById('start-form');
    if (!form) return;

    // ── Modes ──────────────────────────────────────────────────────────
    const filesLabel = document.getElementById('files-label');
    const filesHelp = document.getElementById('files-help');
    const FILES_TEXT = {
        existing: ['Add .nde files to the folder (optional)', 'Only needed for files that aren\'t in the folder yet; they\'re copied into it.'],
        new: ['The job\'s .nde files', 'Copied into the new folder. Select them all at once (Ctrl+A in the folder).'],
        none: ['The job\'s .nde files', 'Select them all at once (Ctrl+A in the folder). Large files take a moment to read.'],
    };

    function mode() {
        const checked = form.querySelector('input[name="folder_mode"]:checked');
        return checked ? checked.value : 'existing';
    }

    function showMode() {
        const current = mode();
        form.querySelectorAll('[data-mode]').forEach(el => { el.hidden = el.dataset.mode !== current; });
        [filesLabel.textContent, filesHelp.textContent] = FILES_TEXT[current];
        // The corrosion form: a job may have no .nde files at all (manual UT); its pictures come from the folder
        if (form.dataset.filesOptional && current !== 'existing') {
            filesLabel.textContent = 'The job\'s .nde files (optional)';
            if (current === 'new') filesHelp.textContent = 'Copied into the new folder. Put the job\'s pictures in the folder too, before going on.';
        }
    }

    form.querySelectorAll('input[name="folder_mode"]').forEach(r => r.addEventListener('change', () => { showMode(); showSource(); }));

    // ── Start from: the .nde files or an existing report (weld report or Short Form) ──
    const reportField = form.querySelector('[data-report-name]');
    const reportName = reportField ? reportField.dataset.reportName : 'report';
    const REPORT_TEXT = {
        existing: [`The ${reportName} (.xlsx, optional)`, "Leave it empty to read the folder's newest .xlsx report."],
        new: [`The ${reportName} (.xlsx)`, null],
        none: [`The ${reportName} (.xlsx)`, null],
    };
    const reportLabel = document.getElementById('report-label');
    const reportHelp = document.getElementById('report-help');
    const reportHelpText = reportHelp ? reportHelp.textContent : '';

    function source() {
        const checked = form.querySelector('input[name="source"]:checked');
        return checked ? checked.value : 'nde';
    }

    function showSource() {
        if (!form.querySelector('input[name="source"]')) return;
        const current = source();
        form.querySelectorAll('[data-source]').forEach(el => { el.hidden = el.dataset.source !== current; });
        const [label, help] = REPORT_TEXT[mode()];
        reportLabel.textContent = label;
        reportHelp.textContent = help ? `${help} ${reportHelpText}` : reportHelpText;
        document.getElementById('start-submit').innerHTML = current === 'report'
            ? '<i class="bi bi-arrow-right"></i> Read the report' : '<i class="bi bi-arrow-right"></i> Read the files';
    }

    form.querySelectorAll('input[name="source"]').forEach(r => r.addEventListener('change', showSource));

    // ── Existing folders: search ───────────────────────────────────────
    const search = document.getElementById('folder-search');
    if (search) {
        const rows = Array.from(document.querySelectorAll('#job-folders .job-folder'));
        const none = document.getElementById('folder-no-matches');
        search.addEventListener('input', () => {
            const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
            let shown = 0;
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                row.hidden = !words.every(w => text.includes(w));
                if (!row.hidden) shown++;
            });
            none.hidden = shown > 0;
        });
    }

    // ── Submit: busy button ────────────────────────────────────────────
    form.addEventListener('submit', () => {
        const button = document.getElementById('start-submit');
        button.disabled = true;
        button.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${source() === 'report' ? 'Reading the report…' : 'Reading the files…'}`;
    });

    showMode();
    showSource();
})();
