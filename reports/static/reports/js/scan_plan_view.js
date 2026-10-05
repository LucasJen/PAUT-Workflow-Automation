// Interactive scan plan drawing: a scene from reports/services/scan_plan/scene.py drawn as SVG
// (the printed drawing is the same scene drawn by Pillow). Scroll to zoom at the cursor, drag the
// background to pan, double-click to fit. Hovering a beam shows its angle, leg, sound path, depth
// and surface distance at that point; anywhere in the part shows the distance from the weld centre
// line and the depth. Dragging the wedge moves the probe and reports the new index offset.
//
// Scene coordinates are inches: weld centre line at x = 0, scanning surface at y = 0, depth down.
// A mirrored scene (270 deg skew) is flipped here, so the readouts use the scene's own x.

(function () {
    const SVG = 'http://www.w3.org/2000/svg';
    const MIN_VIEW_WIDTH = 0.05;   // in: the closest zoom
    const HOVER_PX = 7;            // a beam this close to the cursor is hovered
    const DASH = '8 6';

    function make(name, attrs = {}, parent = null) {
        const node = document.createElementNS(SVG, name);
        for (const [key, value] of Object.entries(attrs)) {
            if (value !== null && value !== undefined) node.setAttribute(key, value);
        }
        if (parent) parent.append(node);
        return node;
    }

    // Nearest point to p on the polyline: {point, segment, along (path length to it), distance}
    function nearestOnPath(points, p) {
        let best = null, travelled = 0;
        for (let i = 0; i < points.length - 1; i++) {
            const [ax, ay] = points[i], [bx, by] = points[i + 1];
            const dx = bx - ax, dy = by - ay, length = Math.hypot(dx, dy);
            const t = length ? Math.max(0, Math.min(1, ((p.x - ax) * dx + (p.y - ay) * dy) / (length * length))) : 0;
            const x = ax + dx * t, y = ay + dy * t, distance = Math.hypot(p.x - x, p.y - y);
            if (!best || distance < best.distance) {
                best = { point: [x, y], segment: i, along: travelled + length * t, distance };
            }
            travelled += length;
        }
        return best;
    }

    class ScanPlanView {
        // options: {format(inches) -> text, step() -> inches the offset snaps to, onOffset(position, inches)}
        constructor(figure, options) {
            this.figure = figure;
            this.options = options;
            this.view = null;                      // [x, y, w, h] once zoomed / panned; null = fit
            this.svg = make('svg', { class: 'scan-plan-svg', role: 'img' });
            this.tip = Object.assign(document.createElement('div'), { className: 'scan-plan-tip', hidden: true });
            this.readout = Object.assign(document.createElement('div'), { className: 'scan-plan-readout' });
            const stage = Object.assign(document.createElement('div'), { className: 'scan-plan-stage' });
            stage.append(this.svg, this.tip);
            figure.prepend(stage, this.readout);
            this.bind();
        }

        update(scene, colours, widthPx, label) {
            this.scene = scene;
            this.colours = colours;
            this.px = widthPx / (scene.x_max - scene.x_min);   // printed px per inch: shape sizes are in those
            this.svg.setAttribute('aria-label', label);
            const width = scene.x_max - scene.x_min, height = scene.y_max - scene.y_min;
            this.fit = [scene.x_min, scene.y_min, width, height];
            this.svg.style.aspectRatio = `${width} / ${height}`;
            if (this.view) {   // keep the user's zoom, at the new shape
                this.view[3] = this.view[2] * height / width;
            }
            this.draw();
            this.applyView();
        }

        resetView() {
            this.view = null;
            this.applyView();
        }

        applyView() {
            this.svg.setAttribute('viewBox', (this.view || this.fit).join(' '));
        }

        X(x) {
            return this.scene.mirror ? this.scene.x_min + this.scene.x_max - x : x;
        }

        pts(points) {
            return points.map(([x, y]) => `${this.X(x)},${y}`).join(' ');
        }

        colour(name) {
            return name ? this.colours[name] : 'none';
        }

        // ── Drawing ──

        draw() {
            this.svg.replaceChildren();
            this.beams = [];
            this.moving = [];                      // groups that follow the probe while it's dragged
            this.dimension = [];
            let group = null, groupName;
            for (const shape of this.scene.shapes) {
                const name = shape.group || '';
                if (!group || name !== groupName) {
                    group = make('g', { class: name ? `scene-${name}` : null }, this.svg);
                    groupName = name;
                    if (name === 'probe' || name === 'beam') this.moving.push(group);
                    if (name === 'dimension') this.dimension.push(group);
                }
                const node = this.shape(shape, group);
                if (name === 'beam') this.beams.push({ shape, node });
            }
            // Hover marks, on top
            this.highlight = make('polyline', { class: 'scan-plan-highlight', fill: 'none', 'vector-effect': 'non-scaling-stroke' }, this.svg);
            this.dot = make('circle', { class: 'scan-plan-dot', r: 3.5 / this.px, 'vector-effect': 'non-scaling-stroke' }, this.svg);
            this.clearHover();
        }

        shape(s, parent) {
            const stroke = { stroke: this.colour(s.stroke), 'stroke-width': s.width || 1, 'vector-effect': 'non-scaling-stroke' };
            switch (s.kind) {
                case 'polygon':
                    return make('polygon', { points: this.pts(s.points), fill: this.colour(s.fill),
                                             ...(s.stroke ? stroke : { stroke: 'none' }) }, parent);
                case 'line':
                    return make('polyline', { points: this.pts(s.points), fill: 'none', 'stroke-linejoin': 'round', ...stroke }, parent);
                case 'dashed':
                    return make('line', { x1: this.X(s.a[0]), y1: s.a[1], x2: this.X(s.b[0]), y2: s.b[1],
                                          'stroke-dasharray': DASH, ...stroke }, parent);
                case 'arrow': {
                    const [tx, ty] = [this.X(s.tip[0]), s.tip[1]], [fx, fy] = [this.X(s.towards[0]), s.towards[1]];
                    const angle = Math.atan2(fy - ty, fx - tx), size = 9 / this.px;
                    const d = [0.45, -0.45].map(a => `M${tx},${ty} L${tx + size * Math.cos(angle + a)},${ty + size * Math.sin(angle + a)}`);
                    return make('path', { d: d.join(' '), fill: 'none', ...stroke, 'stroke-width': 1.4 }, parent);
                }
                case 'text': {
                    const baseline = { m: 'central', b: 'text-after-edge', t: 'text-before-edge' }[(s.anchor || 'mm')[1]];
                    const text = make('text', {
                        x: this.X(s.at[0]), y: s.at[1], 'font-size': s.size / this.px, 'font-family': 'Arial, sans-serif',
                        'text-anchor': 'middle', 'dominant-baseline': baseline, fill: this.colour(s.stroke || 'text'),
                        ...(s.halo ? { stroke: '#fff', 'stroke-width': 6 / this.px, 'paint-order': 'stroke', 'stroke-linejoin': 'round' } : {}),
                    }, parent);
                    text.textContent = s.text;
                    return text;
                }
                case 'cells': {
                    const [w, h] = s.size;
                    const d = s.centres.map(([x, y]) => `M${this.X(x) - w / 2},${y - h / 2}h${w}v${h}h${-w}z`).join('');
                    // Edges overlap a hair so neighbouring cells don't show seams
                    return make('path', { d, fill: this.colour(s.fill), stroke: this.colour(s.fill), 'stroke-width': 0.6,
                                          'vector-effect': 'non-scaling-stroke' }, parent);
                }
            }
            return null;
        }

        // ── Pointer: hover readouts, pan, probe drag, zoom ──

        toScene(event) {
            const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(this.svg.getScreenCTM().inverse());
            return { svgX: point.x, x: this.X(point.x), y: point.y };   // X() is its own inverse
        }

        unitsPerPixel() {
            return (this.view || this.fit)[2] / this.svg.getBoundingClientRect().width;
        }

        bind() {
            const svg = this.svg;
            svg.addEventListener('pointerdown', event => {
                if (event.button !== 0 || !this.scene) return;
                const start = this.toScene(event);
                const onProbe = event.target.closest('.scene-probe');
                this.drag = onProbe
                    ? { kind: 'probe', start, offset: this.scene.meta.index_offset, moved: false }
                    : { kind: 'pan', clientX: event.clientX, clientY: event.clientY, view: [...(this.view || this.fit)] };
                svg.setPointerCapture(event.pointerId);
                svg.classList.add(onProbe ? 'is-moving-probe' : 'is-panning');
                this.clearHover();
            });
            svg.addEventListener('pointermove', event => {
                if (!this.scene) return;
                if (this.drag?.kind === 'pan') this.pan(event);
                else if (this.drag?.kind === 'probe') this.moveProbe(event);
                else this.hover(event);
            });
            const end = event => {
                if (!this.drag) return;
                const drag = this.drag;
                this.drag = null;
                svg.classList.remove('is-moving-probe', 'is-panning');
                if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
                if (drag.kind === 'probe') {
                    if (drag.moved && event.type === 'pointerup') {
                        this.options.onOffset(this.scene.meta.position, drag.newOffset);
                    } else {   // cancelled: put it back
                        this.moving.forEach(g => g.removeAttribute('transform'));
                        this.dimension.forEach(g => { g.style.display = ''; });
                        this.tip.hidden = true;
                    }
                }
            };
            svg.addEventListener('pointerup', end);
            svg.addEventListener('pointercancel', end);
            svg.addEventListener('pointerleave', () => { if (!this.drag) this.clearHover(); });
            svg.addEventListener('dblclick', () => this.resetView());
            svg.addEventListener('wheel', event => {
                if (!this.scene) return;
                event.preventDefault();
                const p = this.toScene(event);
                const [x, y, w, h] = this.view || this.fit;
                const factor = Math.exp(event.deltaY * 0.0015);
                const width = Math.min(Math.max(w * factor, MIN_VIEW_WIDTH), this.fit[2] * 4);
                const f = width / w;
                this.view = [p.svgX - (p.svgX - x) * f, p.y - (p.y - y) * f, width, h * f];
                this.applyView();
            }, { passive: false });
        }

        pan(event) {
            const scale = this.unitsPerPixel();
            const [x, y, w, h] = this.drag.view;
            this.view = [x - (event.clientX - this.drag.clientX) * scale, y - (event.clientY - this.drag.clientY) * scale, w, h];
            this.applyView();
        }

        moveProbe(event) {
            const drag = this.drag, here = this.toScene(event);
            const step = this.options.step();
            // Towards the weld (+x in the scene) shortens the offset; never past the centre line
            let offset = drag.offset - (here.x - drag.start.x);
            offset = Math.max(0, Math.round(offset / step) * step);
            const shift = drag.offset - offset;                    // scene x the probe moved
            drag.moved = drag.moved || Math.abs(shift) > 1e-9;
            drag.newOffset = offset;
            const svgShift = this.scene.mirror ? -shift : shift;
            this.moving.forEach(g => g.setAttribute('transform', `translate(${svgShift} 0)`));
            this.dimension.forEach(g => { g.style.display = 'none'; });
            const rows = [['Index offset', this.options.format(offset)]];
            if (offset < this.scene.meta.toe - 1e-9) {   // the suggestion never goes there
                rows.push(['Wedge front', `on the cap (toe ${this.options.format(this.scene.meta.toe)})`]);
            }
            this.showTip(event, rows);
        }

        hover(event) {
            const p = this.toScene(event);
            const reach = HOVER_PX * this.unitsPerPixel();
            let best = null;
            for (const beam of this.beams) {
                const near = nearestOnPath(beam.shape.points, p);
                if (near && near.distance <= reach && (!best || near.distance < best.near.distance)) best = { beam, near };
            }
            const t = this.scene.meta.thickness;
            const inPart = p.y >= 0 && p.y <= t;
            const format = this.options.format;
            this.readout.textContent = inPart
                ? `Cursor: ${format(Math.abs(p.x))} from the weld C/L, depth ${format(p.y)}`
                : '';
            if (!best) {
                this.clearHover(false);
                return;
            }
            const { shape } = best.beam, { point: [x, y], segment, along } = best.near;
            const points = shape.points;
            this.highlight.setAttribute('points', this.pts(points));
            this.highlight.style.display = '';
            this.dot.setAttribute('cx', this.X(x));
            this.dot.setAttribute('cy', y);
            this.dot.style.display = '';
            const exit = points[0][0];
            const rows = [
                ['Beam', `${+shape.data.angle.toFixed(1)}°, leg ${segment + 1}`],
                ['Sound path', `${format(along)} of ${format(shape.data.sound_path)}`],
                ['Depth', format(y)],
                ['From exit point', format(Math.abs(x - exit))],
                ['From weld C/L', format(Math.abs(x))],
            ];
            if (points.length > 1) rows.push(['Half skip', format(Math.abs(points[1][0] - exit))]);
            this.showTip(event, rows);
        }

        showTip(event, rows) {
            this.tip.replaceChildren(...rows.map(([label, value]) => {
                const row = document.createElement('div');
                row.append(Object.assign(document.createElement('span'), { textContent: label }),
                           Object.assign(document.createElement('strong'), { textContent: value }));
                return row;
            }));
            this.tip.hidden = false;
            const box = this.tip.parentElement.getBoundingClientRect();
            let left = event.clientX - box.left + 14, top = event.clientY - box.top + 14;
            if (left + this.tip.offsetWidth > box.width) left = event.clientX - box.left - this.tip.offsetWidth - 14;
            if (top + this.tip.offsetHeight > box.height) top = Math.max(0, event.clientY - box.top - this.tip.offsetHeight - 14);
            this.tip.style.left = `${left}px`;
            this.tip.style.top = `${top}px`;
        }

        clearHover(readout = true) {
            if (this.highlight) this.highlight.style.display = 'none';
            if (this.dot) this.dot.style.display = 'none';
            this.tip.hidden = true;
            if (readout) this.readout.textContent = '';
        }
    }

    window.ScanPlanView = ScanPlanView;
})();
