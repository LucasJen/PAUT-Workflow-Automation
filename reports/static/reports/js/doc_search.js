// Dashboard Documentation card: the search box refreshes the list from document-search as you type
// (all matches; an empty box shows the 10 most recently used). Without JS the form submits instead.

(function () {
    const form = document.getElementById('doc-search');
    const results = document.getElementById('doc-results');
    if (!form || !results) return;
    const input = form.querySelector('input[name="q"]');
    let timer = null, latest = 0;

    async function refresh() {
        const ticket = ++latest;
        const url = `${form.dataset.searchUrl}?q=${encodeURIComponent(input.value)}`;
        try {
            const html = await (await fetch(url)).text();
            if (ticket === latest) results.innerHTML = html;   // ignore answers to older keystrokes
        } catch (e) { /* keep the current list */ }
    }

    form.addEventListener('submit', e => { e.preventDefault(); refresh(); });
    input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(refresh, 200);
    });
    // An opened document moves to the top; refresh once the new tab has been opened
    results.addEventListener('click', e => {
        if (e.target.closest('a[target="_blank"]')) setTimeout(refresh, 500);
    });
})();
