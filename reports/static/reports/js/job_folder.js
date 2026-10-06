// Guided Creation, step 1 (start_from_files.html): the job folder modes (existing / new / files
// only), the folder list's search, and the working folder's Add link.

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
    }

    form.querySelectorAll('input[name="folder_mode"]').forEach(r => r.addEventListener('change', showMode));

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
        button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Reading the files…';
    });

    // ── Working folder: Add ────────────────────────────────────────────
    const change = document.getElementById('root-change');
    if (change) {
        change.addEventListener('click', () => {
            document.getElementById('root-edit').hidden = false;
            change.hidden = true;
            document.querySelector('#root-edit input').focus();
        });
    }

    showMode();
})();
