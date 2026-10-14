// Zoom sliders in a view's panel head: one across (↔) and one down (↕), each from the fitted view
// (1x) to the view's most zoom, on a log scale. Moving one zooms just that axis about the middle of
// the view (view.setZoom); they follow the view after each draw, so the wheel, fit and double-click
// move them too. Double-click a slider to put that axis back to fit.
// A view brings: zoomFactors() -> [across, down], setZoom('x' | 'y', k), maxZoom(), draw().

window.ZoomSliders = (function () {
    const STEPS = 1000;

    function attach(view, holder, names = ['Horizontal zoom', 'Vertical zoom']) {
        const sliders = ['x', 'y'].map((axis, i) => {
            const label = document.createElement('label');
            label.className = 'analysis-zoom-axis';
            label.title = `${names[i]} (double-click: fit)`;
            const icon = document.createElement('i');
            icon.className = `bi ${axis === 'x' ? 'bi-arrows' : 'bi-arrows-vertical'}`;
            const input = Object.assign(document.createElement('input'), {
                type: 'range', min: 0, max: STEPS, step: 1, value: 0, className: 'form-range',
            });
            input.setAttribute('aria-label', names[i]);
            const toZoom = v => Math.pow(view.maxZoom(), v / STEPS);
            const toValue = k => Math.round(Math.max(0, Math.min(1, Math.log(Math.max(k, 1)) / Math.log(view.maxZoom()))) * STEPS);
            input.addEventListener('input', () => view.setZoom(axis, toZoom(+input.value)));
            input.addEventListener('dblclick', () => view.setZoom(axis, 1));
            const slider = { input, toValue, name: names[i], held: false };
            input.addEventListener('pointerdown', () => { slider.held = true; });
            for (const type of ['pointerup', 'pointercancel', 'change']) input.addEventListener(type, () => { slider.held = false; });
            label.append(icon, input);
            holder.append(label);
            return slider;
        });
        const follow = () => {
            const factors = view.zoomFactors();
            sliders.forEach((s, i) => {
                const value = s.toValue(factors[i]);
                if (+s.input.value !== value && !s.held) s.input.value = value;   // not under the pointer
                s.input.parentElement.title = `${s.name}: ${factors[i].toFixed(factors[i] < 10 ? 1 : 0)}x (double-click: fit)`;
            });
        };
        const draw = view.draw.bind(view);
        view.draw = (...args) => { const out = draw(...args); follow(); return out; };
        follow();
    }

    return { attach };
})();
