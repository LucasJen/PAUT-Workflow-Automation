// The Analysis app's frame: the left rail opens one panel at a time beside the views (the open
// panel is remembered in this browser), the readings column can be hidden, and the theme toggles
// like the rest of the app. Whoever lays out the views listens with onChange (the views' sizes
// change when a panel opens or closes).

window.AnalysisShell = (function () {
    const app = document.getElementById('analysis');
    if (!app) return null;
    const drawer = document.getElementById('drawer');
    const title = document.getElementById('drawer-title');
    const buttons = [...document.querySelectorAll('.analysis-rail-button')];
    const bodies = [...document.querySelectorAll('[data-panel-body]')];
    const listeners = [];
    const get = key => { try { return localStorage.getItem(key); } catch { return null; } };
    const set = (key, value) => { try { localStorage.setItem(key, value); } catch { /* not kept */ } };
    let current = null;

    const changed = () => listeners.forEach(fn => fn(current));

    function open(name) {
        const body = bodies.find(b => b.dataset.panelBody === name);
        if (!body) return;
        current = name;
        bodies.forEach(b => { b.hidden = b !== body; });
        buttons.forEach(b => {
            const on = b.dataset.panel === name;
            b.classList.toggle('is-active', on);
            b.setAttribute('aria-pressed', on);
        });
        title.textContent = body.dataset.title;
        drawer.hidden = false;
        app.classList.add('has-drawer');
        app.classList.toggle('has-wide-drawer', 'wide' in body.dataset);
        set('analysisPanel', name);
        changed();
    }

    function close() {
        if (!current) return;
        current = null;
        drawer.hidden = true;
        app.classList.remove('has-drawer');
        buttons.forEach(b => { b.classList.remove('is-active'); b.setAttribute('aria-pressed', 'false'); });
        set('analysisPanel', '');
        changed();
    }

    const toggle = name => (current === name ? close() : open(name));
    buttons.forEach(b => b.addEventListener('click', () => toggle(b.dataset.panel)));
    document.getElementById('drawer-close').addEventListener('click', close);

    // The readings column
    const grid = document.getElementById('analysis-grid');
    const readingsButton = document.getElementById('readings-toggle');
    function showReadings(on) {
        grid.classList.toggle('no-readings', !on);
        readingsButton.setAttribute('aria-pressed', on);
        readingsButton.classList.toggle('is-active', on);
        set('analysisReadings', on ? '1' : '0');
        changed();
    }
    readingsButton.addEventListener('click', () => showReadings(grid.classList.contains('no-readings')));

    // Light / dark, shared with the rest of the app
    const root = document.documentElement;
    const themeButton = document.getElementById('theme-toggle');
    const showTheme = () => {
        const dark = root.getAttribute('data-bs-theme') === 'dark';
        themeButton.querySelector('i').className = dark ? 'bi bi-sun' : 'bi bi-moon';
        themeButton.title = dark ? 'Light mode' : 'Dark mode';
    };
    themeButton.addEventListener('click', () => {
        const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-bs-theme', next);
        set('theme', next);
        showTheme();
    });
    showTheme();

    // Full screen: the whole window
    document.getElementById('full-screen').addEventListener('click', () => {
        if (document.fullscreenElement) document.exitFullscreen();
        else root.requestFullscreen?.().catch(() => {});
    });

    showReadings(get('analysisReadings') !== '0');
    const saved = get('analysisPanel');
    if (saved) open(saved);

    return {
        open, close, toggle,
        get current() { return current; },
        toggleReadings: () => showReadings(grid.classList.contains('no-readings')),
        onChange: fn => listeners.push(fn),
    };
})();
