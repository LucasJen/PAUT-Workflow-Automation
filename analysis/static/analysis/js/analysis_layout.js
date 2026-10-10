// The Analysis page's panel layout: the grid fills the window down to its bottom edge, and drag
// handles on the gaps resize the panels - between the two view columns, between the views and the
// readings column, and between the two rows. Sizes are remembered per layout (A-S, A-S-C, A-B-C-S)
// in this browser. The views redraw themselves when their panels change size (ResizeObserver).

window.AnalysisLayout = (function () {
    const MIN_VIEW = 160, MIN_SIDE = 200, MAX_SIDE = 520, MIN_ROW = 120;

    function tracks(value) {
        return value.split(' ').map(parseFloat).filter(Number.isFinite);
    }

    return function AnalysisLayout(grid) {
        const handles = {};
        for (const name of ['col', 'side', 'row']) {
            const el = Object.assign(document.createElement('div'), {
                className: `analysis-splitter analysis-splitter-${name === 'row' ? 'row' : 'col'}`,
            });
            el.dataset.split = name;
            el.title = name === 'row' ? 'Drag to resize the rows' : 'Drag to resize the columns';
            grid.append(el);
            handles[name] = el;
        }
        const key = () => `analysisSizes:${grid.dataset.layout}`;
        const twoRows = () => grid.dataset.layout !== 'A-S';

        function load() {
            let sizes = null;
            try { sizes = JSON.parse(localStorage.getItem(key()) || 'null'); } catch { sizes = null; }
            for (const name of ['c1', 'c2', 'r1', 'r2']) grid.style.removeProperty(`--${name}`);
            grid.style.removeProperty('--side');
            if (sizes) {
                for (const name of ['c1', 'c2', 'r1', 'r2']) if (sizes[name]) grid.style.setProperty(`--${name}`, `${sizes[name]}fr`);
                if (sizes.side) grid.style.setProperty('--side', `${sizes.side}px`);
            }
        }

        function save(partial) {
            let sizes = {};
            try { sizes = JSON.parse(localStorage.getItem(key()) || '{}') || {}; } catch { sizes = {}; }
            try { localStorage.setItem(key(), JSON.stringify({ ...sizes, ...partial })); } catch { /* not kept */ }
        }

        /** Fills the window from the grid's top edge down; places the handles on the gaps. */
        function fit() {
            if (getComputedStyle(handles.col).display === 'none') return;   // narrow screen: stacked
            const top = grid.getBoundingClientRect().top;
            const full = document.fullscreenElement && document.fullscreenElement.contains(grid);
            grid.style.height = `${Math.max(360, window.innerHeight - top - (full ? 8 : 12))}px`;
            place();
        }

        function place() {
            const style = getComputedStyle(grid);
            const cols = tracks(style.gridTemplateColumns), rows = tracks(style.gridTemplateRows);
            const gap = parseFloat(style.columnGap) || 0;
            if (cols.length < 3) return;
            const height = grid.clientHeight;
            const x1 = cols[0] + gap / 2, x2 = cols[0] + cols[1] + gap * 1.5;
            const rowSplit = twoRows() && rows.length >= 2 ? rows[0] + gap / 2 : null;
            Object.assign(handles.col.style, {
                left: `${x1}px`, top: '0px',
                // On A-S-C the C-scan runs under both columns: the column handle stops at the first row
                height: `${grid.dataset.layout === 'A-S-C' && rowSplit !== null ? rows[0] : height}px`,
            });
            Object.assign(handles.side.style, { left: `${x2}px`, top: '0px', height: `${height}px` });
            handles.row.hidden = rowSplit === null;
            if (rowSplit !== null) Object.assign(handles.row.style, { top: `${rowSplit}px`, left: '0px', width: `${cols[0] + cols[1] + gap}px` });
        }

        function drag(name, e) {
            e.preventDefault();
            const handle = handles[name];
            handle.setPointerCapture(e.pointerId);
            handle.classList.add('is-dragging');
            document.body.classList.add('analysis-resizing');
            const style = getComputedStyle(grid);
            const cols = tracks(style.gridTemplateColumns), rows = tracks(style.gridTemplateRows);
            const start = { x: e.clientX, y: e.clientY, cols, rows };
            const move = ev => {
                const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
                if (name === 'col') {
                    const total = start.cols[0] + start.cols[1];
                    const a = Math.min(Math.max(start.cols[0] + dx, MIN_VIEW), total - MIN_VIEW);
                    grid.style.setProperty('--c1', `${a}fr`);
                    grid.style.setProperty('--c2', `${total - a}fr`);
                } else if (name === 'side') {
                    const side = Math.min(Math.max(start.cols[2] - dx, MIN_SIDE), MAX_SIDE);
                    grid.style.setProperty('--side', `${side}px`);
                } else {
                    const total = start.rows[0] + start.rows[1];
                    const a = Math.min(Math.max(start.rows[0] + dy, MIN_ROW), total - MIN_ROW);
                    grid.style.setProperty('--r1', `${a}fr`);
                    grid.style.setProperty('--r2', `${total - a}fr`);
                }
                place();
            };
            const end = () => {
                handle.removeEventListener('pointermove', move);
                handle.removeEventListener('pointerup', end);
                handle.removeEventListener('pointercancel', end);
                handle.classList.remove('is-dragging');
                document.body.classList.remove('analysis-resizing');
                const s = getComputedStyle(grid);
                const c = tracks(s.gridTemplateColumns), r = tracks(s.gridTemplateRows);
                save(name === 'row' ? { r1: r[0], r2: r[1] } : name === 'side' ? { side: c[2] } : { c1: c[0], c2: c[1] });
            };
            handle.addEventListener('pointermove', move);
            handle.addEventListener('pointerup', end);
            handle.addEventListener('pointercancel', end);
        }

        for (const [name, el] of Object.entries(handles)) {
            el.addEventListener('pointerdown', e => drag(name, e));
            el.addEventListener('dblclick', () => {   // back to the layout's usual sizes
                try { localStorage.removeItem(key()); } catch { /* nothing kept */ }
                load();
                place();
            });
        }
        window.addEventListener('resize', fit);
        document.addEventListener('fullscreenchange', () => requestAnimationFrame(fit));
        new ResizeObserver(place).observe(grid);

        return {
            /** Call after the layout changes: its own sizes, then fill the window. */
            refresh() { load(); requestAnimationFrame(fit); },
            fit,
        };
    };
})();
