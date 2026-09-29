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
        duplicateBtn.hidden = checked !== 1;
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
        if (row) openRow(row, e.ctrlKey || e.metaKey);
    });

    tbody.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.target.matches('tr[data-href]')) openRow(e.target, false);
    });

    // ── Search ─────────────────────────────────────────────────────────

    const search = document.getElementById('list-search');
    if (search) {
        search.addEventListener('input', () => {
            const keyword = search.value.trim().toLowerCase();
            let shown = 0;
            rows().forEach(r => {
                const match = !keyword || r.textContent.toLowerCase().includes(keyword);
                r.hidden = !match;
                if (match) shown++;
            });
            noMatches.hidden = shown > 0;
            updateBulkBar();
        });
    }

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
