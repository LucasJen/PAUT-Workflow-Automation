// Shared behaviour for list pages (components/list_page.html):
// row selection + bulk bar, click-to-open rows, search, column sorting.

(function () {
    const table = document.getElementById('list-table');
    if (!table) return;

    const tbody = table.tBodies[0];
    const rows = () => Array.from(tbody.rows);
    const selectAll = document.getElementById('select-all');
    const bulkBar = document.getElementById('bulk-bar');
    const bulkCount = document.getElementById('bulk-count');
    const duplicateBtn = document.getElementById('duplicate-btn');
    const noMatches = document.getElementById('no-matches');

    // ── Selection ──────────────────────────────────────────────────────

    function updateBulkBar() {
        const checked = tbody.querySelectorAll('.row-check:checked').length;
        bulkBar.classList.toggle('visible', checked > 0);
        bulkCount.textContent = `${checked} selected`;
        if (duplicateBtn) duplicateBtn.hidden = checked !== 1;
        const visible = rows().filter(r => !r.hidden);
        selectAll.checked = visible.length > 0 && visible.every(r => r.querySelector('.row-check').checked);
    }

    tbody.addEventListener('change', e => {
        if (!e.target.classList.contains('row-check')) return;
        e.target.closest('tr').classList.toggle('selected', e.target.checked);
        updateBulkBar();
    });

    selectAll.addEventListener('change', () => {
        rows().filter(r => !r.hidden).forEach(r => {
            r.querySelector('.row-check').checked = selectAll.checked;
            r.classList.toggle('selected', selectAll.checked);
        });
        updateBulkBar();
    });

    // ── Sticky header: show a divider once it is pinned to the top ────
    const header = document.getElementById('list-header');
    if (header) {
        const markStuck = () => {
            const top = parseFloat(getComputedStyle(header).top) || 0;
            header.classList.toggle('is-stuck', window.scrollY > 0 && header.getBoundingClientRect().top <= top + 0.5);
        };
        window.addEventListener('scroll', markStuck, { passive: true });
        window.addEventListener('resize', markStuck);
        markStuck();
    }

    // ── Shift-click range selection ────────────────────────────────────
    // Shift-clicking a checkbox (or anywhere on a row) sets every visible row between the last
    // clicked row and this one to the same state. Rows hidden by the search are skipped.

    let anchor = null;  // the last row clicked without Shift

    function setChecked(row, checked) {
        row.querySelector('.row-check').checked = checked;
        row.classList.toggle('selected', checked);
    }

    function selectRange(row, checked) {
        const visible = rows().filter(r => !r.hidden);
        const from = visible.indexOf(anchor);
        const to = visible.indexOf(row);
        if (from < 0 || to < 0) {
            setChecked(row, checked);
        } else {
            visible.slice(Math.min(from, to), Math.max(from, to) + 1).forEach(r => setChecked(r, checked));
        }
        updateBulkBar();
    }

    // Clear: untick every row (including rows hidden by the search) and restart range selection
    document.getElementById('clear-selection').addEventListener('click', () => {
        rows().forEach(r => setChecked(r, false));
        anchor = null;
        updateBulkBar();
    });

    // Stop the browser from highlighting text while shift-clicking rows
    tbody.addEventListener('mousedown', e => {
        if (e.shiftKey && e.target.closest('tr')) e.preventDefault();
    });

    tbody.addEventListener('click', e => {
        const box = e.target.closest('.row-check');
        if (!box) return;
        const row = box.closest('tr');
        if (e.shiftKey && anchor) selectRange(row, box.checked);  // the click has already toggled the box
        anchor = row;
    });

    // ── Click / keyboard to open ───────────────────────────────────────

    function openRow(row, newTab) {
        if (!row.dataset.href) return;
        if (newTab) window.open(row.dataset.href, '_blank');
        else window.location.href = row.dataset.href;
    }

    rows().forEach(r => { if (r.dataset.href) r.tabIndex = 0; });

    tbody.addEventListener('click', e => {
        if (e.target.closest('input, a, button, label, .col-check')) return;
        const row = e.target.closest('tr');
        if (!row) return;
        if (e.shiftKey) {
            // Shift-click on a row selects (instead of opening), extending from the last clicked row
            if (anchor) {
                selectRange(row, true);
            } else {
                setChecked(row, !row.querySelector('.row-check').checked);
                updateBulkBar();
            }
            anchor = row;
            return;
        }
        openRow(row, e.ctrlKey || e.metaKey);
    });

    tbody.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.target.matches('tr[data-href]')) openRow(e.target, false);
    });

    // ── Search and filters ─────────────────────────────────────────────
    // A row is shown when it has the search text and each filter's value (its data-<filter>)

    const search = document.getElementById('list-search');
    const filters = Array.from(document.querySelectorAll('.list-filter'));

    function applyFilters() {
        const keyword = (search?.value || '').trim().toLowerCase();
        let shown = 0;
        rows().forEach(r => {
            const match = (!keyword || r.textContent.toLowerCase().includes(keyword))
                && filters.every(f => !f.value || r.dataset[f.dataset.filter] === f.value);
            r.hidden = !match;
            if (match) shown++;
        });
        noMatches.hidden = shown > 0;
        updateBulkBar();
    }

    search?.addEventListener('input', applyFilters);
    filters.forEach(f => f.addEventListener('change', applyFilters));

    // A link may open the list filtered: ?status=draft picks that option (the dashboard's Drafts tile)
    const params = new URLSearchParams(location.search);
    let preset = false;
    filters.forEach(f => {
        const value = params.get(f.dataset.filter);
        if (value && Array.from(f.options || []).some(o => o.value === value)) {
            f.value = value;
            preset = true;
        }
    });
    if (preset) applyFilters();

    // ── Sorting ────────────────────────────────────────────────────────

    const NUMBER = /^-?\d+(\.\d+)?$/;
    let sortIndex = null;
    let sortAsc = true;

    function cellValue(row, index) {
        const cell = row.cells[index];
        if (!cell) return '';
        return (cell.dataset.sortValue ?? cell.textContent).trim();
    }

    table.tHead.querySelectorAll('th.sortable').forEach(th => {
        th.tabIndex = 0;
        const sort = () => {
            const index = th.cellIndex;
            sortAsc = sortIndex === index ? !sortAsc : true;
            sortIndex = index;
            table.tHead.querySelectorAll('th.sortable').forEach(h => {
                h.classList.remove('asc', 'desc');
                h.removeAttribute('aria-sort');
            });
            th.classList.add(sortAsc ? 'asc' : 'desc');
            th.setAttribute('aria-sort', sortAsc ? 'ascending' : 'descending');

            const sorted = rows().sort((a, b) => {
                const av = cellValue(a, index);
                const bv = cellValue(b, index);
                // Blank values always sort last
                if (!av && bv) return 1;
                if (av && !bv) return -1;
                const cmp = NUMBER.test(av) && NUMBER.test(bv)
                    ? Number(av) - Number(bv)
                    : av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
                return sortAsc ? cmp : -cmp;
            });
            sorted.forEach(r => tbody.appendChild(r));
        };
        th.addEventListener('click', sort);
        th.addEventListener('keydown', e => { if (e.key === 'Enter') sort(); });
    });

    updateBulkBar();
})();
