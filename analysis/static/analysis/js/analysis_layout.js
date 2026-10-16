// The Analysis page's panel layout: the grid fills the window down to its bottom edge, and drag
// handles on the gaps resize the panels - between the two view columns, between the views and the
// readings column, and between the two rows. Sizes are remembered per layout (A-S, A-S-C, A-B-C-S)
// in this browser. The views redraw themselves when their panels change size (ResizeObserver).
// Drag a view by its header onto another to swap their places (kept per layout), and turn any view a
// quarter at a time with the button in its header (kept per view; view_turn.js does the rest). Presets
// keep a layout as it is - its views, their places, turns and sizes - under a name: they're listed in
// the layout select, and saved / deleted from the bookmark menu beside it.

window.AnalysisLayout = (function () {
    const MIN_VIEW = 160, MIN_SIDE = 120, MAX_SIDE = 520, MIN_ROW = 120;
    // Each layout's views in their usual places p1, p2...
    const VIEWS = { 'A-S': ['sscan', 'ascan'], 'A-S-C': ['sscan', 'ascan', 'cscan'], 'A-B-C-S': ['cscan', 'sscan', 'bscan', 'ascan'] };
    const PRESETS = 'analysisLayoutPresets', TURNS = 'analysisTurns';

    function read(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; }
    }
    function write(key, value) {
        try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch { /* not kept */ }
    }

    function tracks(value) {
        return value.split(' ').map(parseFloat).filter(Number.isFinite);
    }

    /** grid: the views' grid; select: the layout select (its presets are added to it). */
    return function AnalysisLayout(grid, select) {
        const handles = {};
        for (const name of ['col', 'side', 'row', 'corner']) {
            const el = Object.assign(document.createElement('div'), {
                className: `analysis-splitter analysis-splitter-${name === 'col' || name === 'side' ? 'col' : name}`,
            });
            el.dataset.split = name;
            el.title = name === 'row' ? 'Drag to resize the rows'
                : name === 'corner' ? 'Drag to resize the columns and rows together' : 'Drag to resize the columns';
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
            handles.row.hidden = handles.corner.hidden = rowSplit === null;
            if (rowSplit !== null) {
                Object.assign(handles.row.style, { top: `${rowSplit}px`, left: '0px', width: `${cols[0] + cols[1] + gap}px` });
                // Where the column and row gaps cross: both at once
                Object.assign(handles.corner.style, { left: `${x1}px`, top: `${rowSplit}px` });
            }
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
                if (name === 'col' || name === 'corner') {
                    const total = start.cols[0] + start.cols[1];
                    const a = Math.min(Math.max(start.cols[0] + dx, MIN_VIEW), total - MIN_VIEW);
                    grid.style.setProperty('--c1', `${a}fr`);
                    grid.style.setProperty('--c2', `${total - a}fr`);
                } else if (name === 'side') {
                    const side = Math.min(Math.max(start.cols[2] - dx, MIN_SIDE), MAX_SIDE);
                    grid.style.setProperty('--side', `${side}px`);
                }
                if (name === 'row' || name === 'corner') {
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
                save(name === 'row' ? { r1: r[0], r2: r[1] } : name === 'side' ? { side: c[2] }
                    : name === 'corner' ? { c1: c[0], c2: c[1], r1: r[0], r2: r[1] } : { c1: c[0], c2: c[1] });
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
        // ── the views' places and turns ──
        const viewPanels = [...grid.querySelectorAll('.analysis-panel[data-view]')];
        const orderKey = () => `analysisOrder:${grid.dataset.layout}`;
        /** The layout's views in place order (p1, p2...): as dragged, else the usual. */
        function order() {
            const usual = VIEWS[grid.dataset.layout] || VIEWS['A-S'];
            const kept = read(orderKey(), null);
            return Array.isArray(kept) && kept.length === usual.length && usual.every(v => kept.includes(v)) ? kept : usual;
        }

        /** Puts each view in its place (or out of the layout) and turns it as kept; true when a turn changed. */
        function arrange() {
            const views = order(), turns = read(TURNS, {});
            let turned = false;
            for (const panel of viewPanels) {
                const i = views.indexOf(panel.dataset.view);
                panel.classList.toggle('is-off', i < 0);
                panel.style.gridArea = i < 0 ? '' : `p${i + 1}`;
                turned = showTurn(panel, turns[panel.dataset.view] || 0) || turned;
            }
            return turned;
        }

        function showTurn(panel, turn) {
            const before = +(panel.dataset.turn || 0);
            if (turn) panel.dataset.turn = turn; else delete panel.dataset.turn;
            const button = panel.querySelector('.analysis-turn');
            button.querySelector('span').textContent = turn ? `${turn}°` : '';
            button.setAttribute('aria-pressed', String(!!turn));
            return before !== turn;
        }

        /** The layout changed by hand: the select no longer shows a preset. */
        function changed() {
            if (select.value.startsWith('preset:')) select.value = grid.dataset.layout;
        }

        for (const panel of viewPanels) {
            const button = Object.assign(document.createElement('button'), {
                type: 'button', className: 'btn btn-sm btn-ghost analysis-turn',
                title: 'Turn the view 90° clockwise (Shift+click: anticlockwise)',
            });
            button.setAttribute('aria-label', 'Turn the view 90 degrees');
            button.append(Object.assign(document.createElement('i'), { className: 'bi bi-arrow-clockwise' }), document.createElement('span'));
            panel.querySelector('.analysis-clear-view').after(button);
            button.addEventListener('click', e => {
                const turns = read(TURNS, {}), view = panel.dataset.view;
                turns[view] = ((turns[view] || 0) + (e.shiftKey ? 270 : 90)) % 360;
                write(TURNS, turns);
                showTurn(panel, turns[view]);
                api.onTurn?.();
                changed();
            });

            // Drag by the header (not its controls) onto another view: the two swap places
            const head = panel.querySelector('.analysis-panel-head');
            head.title = 'Drag onto another view to swap their places';
            head.addEventListener('pointerdown', e => {
                if (e.button !== 0 || e.target.closest('button, select, input, label, a, .analysis-range')) return;
                e.preventDefault();
                head.setPointerCapture(e.pointerId);
                const start = { x: e.clientX, y: e.clientY };
                let moving = false, target = null;
                const move = ev => {
                    if (!moving && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return;
                    if (!moving) {
                        moving = true;
                        panel.classList.add('is-moving');
                        document.body.classList.add('analysis-moving');
                    }
                    const over = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.analysis-panel[data-view]');
                    const next = over && over !== panel && grid.contains(over) && !over.classList.contains('is-off') ? over : null;
                    if (next === target) return;
                    target?.classList.remove('is-drop-target');
                    target = next;
                    target?.classList.add('is-drop-target');
                };
                const end = () => {
                    head.removeEventListener('pointermove', move);
                    head.removeEventListener('pointerup', end);
                    head.removeEventListener('pointercancel', end);
                    panel.classList.remove('is-moving');
                    document.body.classList.remove('analysis-moving');
                    target?.classList.remove('is-drop-target');
                    if (!target) return;
                    const views = [...order()];
                    const a = views.indexOf(panel.dataset.view), b = views.indexOf(target.dataset.view);
                    [views[a], views[b]] = [views[b], views[a]];
                    write(orderKey(), views);
                    arrange();
                    place();
                    changed();
                };
                head.addEventListener('pointermove', move);
                head.addEventListener('pointerup', end);
                head.addEventListener('pointercancel', end);
            });
        }

        // ── presets ──
        const menu = document.getElementById('layout-presets-menu'), menuButton = document.getElementById('layout-presets');
        const nameInput = document.getElementById('layout-preset-name'), list = document.getElementById('layout-preset-list');
        const presets = () => read(PRESETS, []).filter(p => p && p.name && VIEWS[p.layout]);
        const closeMenu = () => { menu.hidden = true; menuButton.setAttribute('aria-expanded', 'false'); };

        /** The presets in the layout select (a group of their own) and in the menu. */
        function showPresets() {
            const shown = select.value;
            select.querySelector('optgroup')?.remove();
            const all = presets();
            if (all.length) {
                const group = Object.assign(document.createElement('optgroup'), { label: 'Presets' });
                group.append(...all.map(p => new Option(p.name, `preset:${p.name}`)));
                select.append(group);
            }
            select.value = shown;
            if (!select.value) select.value = grid.dataset.layout;
            list.replaceChildren(...all.map(p => {
                const use = Object.assign(document.createElement('button'), { type: 'button', textContent: p.name, title: `Use ${p.name}` });
                use.addEventListener('click', () => {
                    select.value = `preset:${p.name}`;
                    select.dispatchEvent(new Event('change'));
                    closeMenu();
                });
                const meta = Object.assign(document.createElement('span'), { className: 'meta', textContent: p.layout });
                const remove = Object.assign(document.createElement('button'), {
                    type: 'button', className: 'btn btn-sm btn-ghost', title: `Delete ${p.name}`, innerHTML: '<i class="bi bi-trash"></i>',
                });
                remove.setAttribute('aria-label', `Delete the preset ${p.name}`);
                remove.addEventListener('click', () => {
                    write(PRESETS, presets().filter(o => o.name !== p.name));
                    if (select.value === `preset:${p.name}`) select.value = grid.dataset.layout;
                    showPresets();
                });
                const row = document.createElement('li');
                row.append(use, meta, remove);
                return row;
            }));
        }

        document.getElementById('layout-preset-form').addEventListener('submit', e => {
            e.preventDefault();
            const name = nameInput.value.trim();
            if (!name) { nameInput.focus(); return; }
            const preset = { name, layout: grid.dataset.layout, order: order(), turns: read(TURNS, {}), sizes: read(key(), null) };
            write(PRESETS, [...presets().filter(p => p.name !== name), preset]);
            nameInput.value = '';
            showPresets();
            select.value = `preset:${name}`;
        });
        menuButton.addEventListener('click', () => {
            if (!menu.hidden) { closeMenu(); return; }
            menu.hidden = false;
            menuButton.setAttribute('aria-expanded', 'true');
            nameInput.value = select.value.startsWith('preset:') ? select.value.slice(7) : '';
            nameInput.focus();
            nameInput.select();
        });
        document.addEventListener('pointerdown', e => { if (!menu.hidden && !e.target.closest('.analysis-presets')) closeMenu(); });
        menu.addEventListener('keydown', e => { if (e.key === 'Escape') { closeMenu(); menuButton.focus(); } });
        showPresets();

        window.addEventListener('resize', fit);
        document.addEventListener('fullscreenchange', () => requestAnimationFrame(fit));
        new ResizeObserver(place).observe(grid);

        const api = {
            /** Call after the layout changes: its views' places, turns and sizes, then fill the window. */
            refresh() {
                if (arrange()) api.onTurn?.();
                load();
                requestAnimationFrame(fit);
            },
            fit,
            /** A preset's value in the select ('preset:name'): keeps its places, turns and sizes as its layout's
             *  own and returns that layout (refresh() then shows it); null for a plain layout. */
            usePreset(value) {
                const preset = presets().find(p => `preset:${p.name}` === value);
                if (!preset) return null;
                const usual = VIEWS[preset.layout];
                const valid = Array.isArray(preset.order) && preset.order.length === usual.length && usual.every(v => preset.order.includes(v));
                write(`analysisOrder:${preset.layout}`, valid ? preset.order : null);
                write(TURNS, preset.turns || {});
                write(`analysisSizes:${preset.layout}`, preset.sizes || null);
                return preset.layout;
            },
            /** Set by the page: redraws the views after a turn (a half turn doesn't resize them). */
            onTurn: null,
        };
        return api;
    };
})();
