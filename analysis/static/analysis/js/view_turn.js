// Turning a view a quarter at a time: analysis_layout.js turns a panel's .analysis-view with CSS (the
// panel's data-turn: 0 / 90 / 180 / 270 degrees clockwise). The views keep drawing and hit-testing in
// their own, unturned axes: point() maps a pointer event into an element's unturned box, upright()
// makes a 2D canvas's text read the right way up on screen (kept inside the canvas), and cursor()
// swaps a resize cursor's direction on a quarter turn.

window.ViewTurn = (function () {
    const COS = [1, 0, -1, 0], SIN = [0, 1, 0, -1];

    /** The quarter turns (0-3) clockwise of the view holding el. */
    function quarters(el) {
        return (Math.round(+(el.closest('[data-turn]')?.dataset.turn || 0) / 90) % 4 + 4) % 4;
    }

    /** A pointer event's point in el's own (unturned) box, CSS px: [x, y, width, height]. */
    function point(el, e) {
        const box = el.getBoundingClientRect();
        const q = quarters(el);
        if (!q) return [e.clientX - box.left, e.clientY - box.top, box.width, box.height];
        const w = el.offsetWidth, h = el.offsetHeight;
        const dx = e.clientX - (box.left + box.width / 2), dy = e.clientY - (box.top + box.height / 2);
        return [w / 2 + dx * COS[q] + dy * SIN[q], h / 2 - dx * SIN[q] + dy * COS[q], w, h];
    }

    /** A CSS cursor for el as seen on screen: ns-resize / ew-resize swap on a quarter turn. */
    function cursor(el, name) {
        if (quarters(el) % 2 === 0) return name;
        return { 'ns-resize': 'ew-resize', 'ew-resize': 'ns-resize', 'row-resize': 'col-resize', 'col-resize': 'row-resize' }[name] || name;
    }

    /** Text on this canvas's 2D context drawn the right way up however its view is turned. */
    function upright(canvas) {
        const ctx = canvas.getContext('2d');
        if (!ctx || ctx.uprightText) return ctx;
        ctx.uprightText = true;
        for (const name of ['fillText', 'strokeText']) {
            const draw = ctx[name].bind(ctx);
            ctx[name] = (text, x, y, ...rest) => {
                const q = quarters(canvas);
                if (!q) return draw(text, x, y, ...rest);
                const m = ctx.getTransform();
                const p = m.transformPoint(new DOMPoint(x, y));
                const W = canvas.width, H = canvas.height;
                // The anchor on screen (canvas pixels, the canvas turned q quarters clockwise)
                const [sx, sy] = [null, [H - p.y, p.x], [W - p.x, H - p.y], [p.y, W - p.x]][q];
                const SW = q % 2 ? H : W, SH = q % 2 ? W : H;
                const scale = Math.hypot(m.a, m.b) || 1;
                const metrics = ctx.measureText(text);
                const tw = metrics.width * scale;
                const asc = (metrics.fontBoundingBoxAscent ?? metrics.actualBoundingBoxAscent) * scale;
                const th = asc + (metrics.fontBoundingBoxDescent ?? metrics.actualBoundingBoxDescent) * scale;
                // The text's box around its anchor as drawn (unturned), then turned with the canvas
                const align = ctx.textAlign, base = ctx.textBaseline;
                const x0 = align === 'right' || align === 'end' ? -tw : align === 'center' ? -tw / 2 : 0;
                const y0 = base === 'top' || base === 'hanging' ? 0 : base === 'middle' ? -th / 2
                    : base === 'bottom' || base === 'ideographic' ? -th : -asc;
                const turn = (dx, dy) => [null, [-dy, dx], [-dx, -dy], [dy, -dx]][q];
                const [ax, ay] = turn(x0, y0), [bx, by] = turn(x0 + tw, y0 + th);
                // Upright, on the same side of the anchor as the turned box - a label stays beside its tick or
                // line, not on it - or centred on it when the anchor is inside the box (centred text)
                const side = (lo, hi, size) => (lo >= -0.5 ? 0 : hi <= 0.5 ? -size : (lo + hi) / 2 - size / 2);
                let left = sx + side(Math.min(ax, bx), Math.max(ax, bx), tw);
                let top = sy + side(Math.min(ay, by), Math.max(ay, by), th);
                // Kept inside: a label along an edge that now runs past the canvas comes back in
                const pad = 2 * (window.devicePixelRatio || 1);
                left = Math.max(pad, Math.min(SW - pad - tw, left));
                top = Math.max(pad, Math.min(SH - pad - th, top));
                const [cx, cy] = [null, [top + asc, H - left], [W - left, H - top - asc], [W - top - asc, left]][q];
                ctx.save();
                ctx.setTransform(1, 0, 0, 1, 0, 0);
                ctx.translate(cx, cy);
                ctx.rotate(-q * Math.PI / 2);
                ctx.scale(scale, scale);
                ctx.textAlign = 'left';
                ctx.textBaseline = 'alphabetic';
                draw(text, 0, 0, ...rest);
                ctx.restore();
            };
        }
        return ctx;
    }

    return { quarters, point, cursor, upright };
})();
