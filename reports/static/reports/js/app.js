// Shared page behaviour: theme toggle, sidebar collapse, confirmation dialogs.

function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
}

function storageSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ }
}

// ── Theme ────────────────────────────────────────────────────────────────

const root = document.documentElement;
const themeBtn = document.getElementById('theme-toggle');

function renderThemeButton() {
    const dark = root.getAttribute('data-bs-theme') === 'dark';
    themeBtn.querySelector('i').className = dark ? 'bi bi-sun' : 'bi bi-moon';
    themeBtn.querySelector('.nav-label').textContent = dark ? 'Light mode' : 'Dark mode';
}

themeBtn.addEventListener('click', () => {
    const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-bs-theme', next);
    storageSet('theme', next);
    renderThemeButton();
});

// Follow OS changes unless the user picked a theme explicitly
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    const stored = storageGet('theme');
    if (stored === 'light' || stored === 'dark') return;
    root.setAttribute('data-bs-theme', e.matches ? 'dark' : 'light');
    renderThemeButton();
});

renderThemeButton();

// ── Sidebar ──────────────────────────────────────────────────────────────

document.getElementById('sidebar-collapse').addEventListener('click', () => {
    const collapsed = root.classList.toggle('sidebar-collapsed');
    storageSet('sidebarCollapsed', collapsed);
});

// Group labels show / hide their links; the closed groups are remembered (see base.html <head>).
// The current page's group starts open even if closed (app.css); its first click goes back to the stored state.
document.querySelectorAll('.nav-group').forEach(group => {
    const name = group.dataset.group;
    const label = group.querySelector('.nav-group-label');
    const closedGroups = () => (root.getAttribute('data-nav-closed') || '').split(' ').filter(Boolean);
    const current = !!group.querySelector('.nav-item-link.active');
    label.setAttribute('aria-expanded', current || !closedGroups().includes(name));
    label.addEventListener('click', () => {
        const closing = label.getAttribute('aria-expanded') === 'true';
        let closed = closedGroups().filter(g => g !== name);
        if (closing) closed.push(name);
        group.classList.add('toggled');
        root.setAttribute('data-nav-closed', closed.join(' '));
        storageSet('navClosed', closed.join(' '));
        label.setAttribute('aria-expanded', !closing);
    });
});

// Mobile: slide-in sidebar, closed by clicking outside it
document.getElementById('sidebar-open').addEventListener('click', e => {
    e.stopPropagation();
    root.classList.add('sidebar-open');
});

document.addEventListener('click', e => {
    if (root.classList.contains('sidebar-open') && !e.target.closest('#sidebar')) {
        root.classList.remove('sidebar-open');
    }
});

// ── Confirmation dialog ──────────────────────────────────────────────────
// Any button with data-confirm="Delete {count} report{s}?" asks before submitting.
// {count} is the number of checked .row-check boxes; {s} pluralises.

const confirmModalEl = document.getElementById('confirm-modal');
let pendingButton = null;

function confirmMessage(button) {
    const count = document.querySelectorAll('.row-check:checked').length;
    return button.dataset.confirm
        .replaceAll('{count}', count)
        .replaceAll('{s}', count === 1 ? '' : 's');
}

document.addEventListener('click', e => {
    const button = e.target.closest('[data-confirm]');
    if (!button) return;
    if (button.dataset.confirmed) {
        delete button.dataset.confirmed;
        return;  // second pass: let the submit go through
    }
    e.preventDefault();

    const message = confirmMessage(button);
    if (!window.bootstrap) {
        if (window.confirm(message)) {
            button.dataset.confirmed = '1';
            button.click();
        }
        return;
    }
    pendingButton = button;
    document.getElementById('confirm-message').textContent = message;
    document.getElementById('confirm-ok').textContent = button.dataset.confirmLabel || 'Delete';
    bootstrap.Modal.getOrCreateInstance(confirmModalEl).show();
});

document.getElementById('confirm-ok').addEventListener('click', () => {
    bootstrap.Modal.getOrCreateInstance(confirmModalEl).hide();
    if (pendingButton) {
        pendingButton.dataset.confirmed = '1';
        pendingButton.click();  // re-click so the button's name (e.g. "delete") is submitted
        pendingButton = null;
    }
});

// ── Slow downloads (e.g. PDFs made by Word) ──────────────────────────────
// Links with data-busy="Preparing…" show that label for a few seconds after a click, since the
// browser gives no feedback while the server prepares a file download.

function showBusy(link) {
    const original = link.innerHTML;
    link.classList.add('busy', 'disabled');
    link.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> ${link.dataset.busy}`;
    return () => {
        link.innerHTML = original;
        link.classList.remove('busy', 'disabled');
    };
}

document.addEventListener('click', e => {
    const link = e.target.closest('a[data-busy]');
    if (!link || link.hasAttribute('download') || link.dataset.confirm || link.classList.contains('busy')) return;
    setTimeout(showBusy(link), 8000);
});

// ── Downloads ─────────────────────────────────────────────────────────────
// The app's download links (<a download>) are fetched here rather than left to the browser: a
// report that can't be made (no Word / Excel, nothing to generate) answers with an error message
// (reports/views/reports.py, _download_error), shown on this page, instead of the browser saving
// an error page as the file.

function showMessage(text, level = 'danger') {
    let box = document.querySelector('main.content > .messages');
    if (!box) {
        box = document.createElement('div');
        box.className = 'messages';
        document.querySelector('main.content')?.prepend(box);
    }
    const alert = document.createElement('div');
    alert.className = `alert alert-${level} alert-dismissible fade show`;
    alert.setAttribute('role', 'alert');
    alert.textContent = text;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close';
    close.dataset.bsDismiss = 'alert';
    close.setAttribute('aria-label', 'Close');
    alert.append(close);
    box.append(alert);
    alert.scrollIntoView({ block: 'nearest' });
}

function attachmentName(response, fallback) {
    const header = response.headers.get('Content-Disposition') || '';
    const encoded = header.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/);
    if (encoded) return decodeURIComponent(encoded[1]);
    const plain = header.match(/filename="?([^";]+)"?/);
    return plain ? plain[1] : fallback;
}

document.addEventListener('click', async e => {
    const link = e.target.closest('a[download]');
    // Left to the browser: other sites' files, modified clicks, and links a confirm dialog held back
    if (!link || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    if (link.classList.contains('busy') || link.protocol === 'blob:' || link.origin !== location.origin) return;
    e.preventDefault();
    const done = link.dataset.busy !== undefined ? showBusy(link) : () => {};
    try {
        const response = await fetch(link.href, { headers: { 'X-Download': '1' }, credentials: 'same-origin' });
        const type = response.headers.get('Content-Type') || '';
        if (!response.ok || type.includes('text/html')) {
            const data = type.includes('application/json') ? await response.json().catch(() => ({})) : {};
            showMessage(data.error || `The download failed (${response.status} ${response.statusText}).`);
            return;
        }
        const url = URL.createObjectURL(await response.blob());
        const save = document.createElement('a');
        save.href = url;
        save.download = attachmentName(response, link.getAttribute('download') || 'download');
        document.body.append(save);
        save.click();   // a blob: link, so this handler leaves it to the browser
        save.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
        showMessage(`The download failed: ${error.message}`);
    } finally {
        done();
    }
});
