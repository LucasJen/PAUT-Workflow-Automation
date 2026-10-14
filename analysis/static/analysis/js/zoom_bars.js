// Zoom bars like OmniPC's: one along the bottom of a view (across) and one down its side (down). The
// track is the whole axis and the thumb the part shown: drag either end of the thumb to zoom, its
// middle to move along the axis, or click the track to centre the thumb there. Double-click a bar to
// fit that axis. The thumbs follow the view after each draw (the wheel, panning, fit, double-click).
// A view brings: axisRange('x' | 'y') -> {full: [a, b], shown: [a, b], flip} | null (flip: the
// highest value at the top), setAxisRange(axis, [a, b]), maxZoom(), draw().

window.ZoomBars = (function () {
    const GRIP = 7;   // px at each end of the thumb that resize it

    function bar(view, axis, el) {
        const vertical = axis === 'y';
        el.classList.add('analysis-zoombar', vertical ? 'is-v' : 'is-h');
        el.title = `${vertical ? 'Vertical' : 'Horizontal'} zoom: drag an end to zoom, the middle to move (double-click: fit)`;
        const thumb = Object.assign(document.createElement('div'), { className: 'analysis-zoombar-thumb' });
        el.append(thumb);
        let held = null;

        // Fractions along the bar (0 = left / top) <-> world values
        const range = () => view.axisRange(axis);
        const toFraction = (r, [a, b]) => {
            const [f0, f1] = r.full, span = f1 - f0 || 1;
            let u0 = (a - f0) / span, u1 = (b - f0) / span;
            if (r.flip) [u0, u1] = [1 - u1, 1 - u0];
            return [Math.max(0, Math.min(1, u0)), Math.max(0, Math.min(1, u1))];
        };
        const toWorld = (r, [u0, u1]) => {
            const [f0, f1] = r.full, span = f1 - f0;
            return r.flip ? [f1 - u1 * span, f1 - u0 * span] : [f0 + u0 * span, f0 + u1 * span];
        };
        const along = e => {
            const box = el.getBoundingClientRect();
            return vertical ? (e.clientY - box.top) / (box.height || 1) : (e.clientX - box.left) / (box.width || 1);
        };
        const length = () => { const box = el.getBoundingClientRect(); return (vertical ? box.height : box.width) || 1; };

        function render() {
            const r = range();
            thumb.hidden = !r;
            if (!r) return;
            const [u0, u1] = toFraction(r, r.shown);
            thumb.style[vertical ? 'top' : 'left'] = `${u0 * 100}%`;
            thumb.style[vertical ? 'height' : 'width'] = `${(u1 - u0) * 100}%`;
            thumb.classList.toggle('is-full', u0 <= 0.001 && u1 >= 0.999);
        }

        el.addEventListener('pointerdown', e => {
            const r = range();
            if (!r || e.button !== 0) return;
            e.preventDefault();
            el.setPointerCapture(e.pointerId);
            let [u0, u1] = toFraction(r, r.shown);
            const u = along(e), grip = GRIP / length();
            let part;
            if (u < u0 - grip || u > u1 + grip) {   // the track: centre the thumb here, then carry on moving it
                const half = (u1 - u0) / 2;
                const c = Math.max(half, Math.min(1 - half, u));
                [u0, u1] = [c - half, c + half];
                view.setAxisRange(axis, toWorld(r, [u0, u1]));
                part = 'move';
            } else if (u1 - u0 > 3 * grip && Math.abs(u - u0) <= grip) part = 'start';
            else if (u1 - u0 > 3 * grip && Math.abs(u - u1) <= grip) part = 'end';
            else if (Math.abs(u - u0) <= grip && u < (u0 + u1) / 2) part = 'start';
            else if (Math.abs(u - u1) <= grip && u > (u0 + u1) / 2) part = 'end';
            else part = 'move';
            held = { part, u, u0, u1, r };
            el.classList.add('is-held');
        });
        el.addEventListener('pointermove', e => {
            if (!held) {   // the cursor says what a press would do
                const r = range();
                if (!r) return;
                const [u0, u1] = toFraction(r, r.shown), u = along(e), grip = GRIP / length();
                const end = (Math.abs(u - u0) <= grip || Math.abs(u - u1) <= grip) && u >= u0 - grip && u <= u1 + grip;
                el.style.cursor = end ? (vertical ? 'ns-resize' : 'ew-resize') : u >= u0 && u <= u1 ? 'grab' : 'pointer';
                return;
            }
            const d = along(e) - held.u;
            const least = 1 / view.maxZoom();
            let { u0, u1 } = held;
            if (held.part === 'move') {
                const shift = Math.max(-u0, Math.min(1 - u1, d));
                u0 += shift; u1 += shift;
            } else if (held.part === 'start') {
                u0 = Math.max(0, Math.min(u1 - least, u0 + d));
            } else {
                u1 = Math.min(1, Math.max(u0 + least, u1 + d));
            }
            view.setAxisRange(axis, toWorld(held.r, [u0, u1]));
        });
        const release = () => { held = null; el.classList.remove('is-held'); };
        el.addEventListener('pointerup', release);
        el.addEventListener('pointercancel', release);
        el.addEventListener('dblclick', () => { const r = range(); if (r) view.setAxisRange(axis, r.full); });
        return render;
    }

    /** Zoom bars for `view` in the elements `across` (under it) and `down` (beside it). */
    function attach(view, across, down) {
        const renders = [bar(view, 'x', across), bar(view, 'y', down)];
        const follow = () => renders.forEach(r => r());
        const draw = view.draw.bind(view);
        view.draw = (...args) => { const out = draw(...args); follow(); return out; };
        follow();
    }

    return { attach };
})();
