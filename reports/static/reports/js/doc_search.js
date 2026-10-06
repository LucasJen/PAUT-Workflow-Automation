// Dashboard Documentation card: the search box and file-type filter refresh the list from
// document-search as you type (all matches; with neither, the 10 most recently used).
// Without JS the form submits instead.

(function () {
    const form = document.getElementById('doc-search');
    const results = document.getElementById('doc-results');
    if (!form || !results) return;
    const input = form.querySelector('input[name="q"]');
    const type = form.querySelector('select[name="type"]');
    let timer = null, latest = 0;

    async function refresh() {
        const ticket = ++latest;
        const params = new URLSearchParams({ q: input.value, type: type.value });
        const url = `${form.dataset.searchUrl}?${params}`;
        try {
            const html = await (await fetch(url)).text();
            if (ticket === latest) results.innerHTML = html;   // ignore answers to older keystrokes
        } catch (e) { /* keep the current list */ }
    }

    form.addEventListener('submit', e => { e.preventDefault(); refresh(); });
    type.addEventListener('change', refresh);
    input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(refresh, 200);
    });
    // An opened document moves to the top; refresh once it has been opened / downloaded
    results.addEventListener('click', e => {
        if (e.target.closest('a[href]')) setTimeout(refresh, 500);
    });
})();
