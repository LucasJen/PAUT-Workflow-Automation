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

document.addEventListener('click', e => {
    const link = e.target.closest('a[data-busy]');
    if (!link || link.dataset.confirm || link.classList.contains('busy')) return;
    const original = link.innerHTML;
    link.classList.add('busy', 'disabled');
    link.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> ${link.dataset.busy}`;
    setTimeout(() => {
        link.innerHTML = original;
        link.classList.remove('busy', 'disabled');
    }, 8000);
});
