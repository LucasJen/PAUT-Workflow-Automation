// Interactive vessel drawing: a scene from reports/services/vessel/scene.py drawn as SVG (the
// printed drawing is the same scene drawn by Pillow). Scroll to zoom at the cursor, drag the
// background to pan, double-click to fit. Shapes carry the item they belong to (nozzle:<row>,
// seam:<number>, boot, part:<...>, mark:<index>): clicking one reports it, and in the editors the
// draggable ones move (nozzles, seams between courses and the boot in the vessel editor; boxes and
// bands in a report's coverage). Drags only preview here; the editor is told the new value in
// inches when the drag ends and redraws from the server.
//
// The drawing isn't to scale (long vessels are squeezed, short courses widened), so positions are
// turned back into inches through the scene's segment table (meta.segments): s runs along the axis
// from the start end, r off the centre line; on screen a horizontal vessel has x = s, y = -r and a
// vertical one x = r, y = -s.

(function () {
    const SVG = 'http://www.w3.org/2000/svg';
    const CLICK_PX = 4;        // a press that moves less than this is a click
    const MAGNET_PX = 8;       // a seam or course end this close pulls a dragged position onto it
    const END_PX = 7;          // half the width of a box / band end's grab strip

    function make(name, attrs = {}, parent = null) {
        const node = document.createElementNS(SVG, name);
        for (const [key, value] of Object.entries(attrs)) {
            if (value !== null && value !== undefined) node.setAttribute(key, value);
        }
        if (parent) parent.append(node);
        return node;
    }

    const BASELINE = { m: 'central', d: 'text-after-edge', s: 'alphabetic', a: 'text-before-edge', t: 'text-before-edge' };
    const ANCHOR = { l: 'start', m: 'middle', r: 'end' };

    class VesselView {
        /**
         * stage: an element to draw in. options:
         *   mode: 'vessel' (drag nozzles, seams, the boot) or 'coverage' (drag / draw boxes and bands)
         *   format(inches): a length as the editor shows it
         *   onClick(item), onNozzle(row, {position, flip}), onSeam(seam, deltaInches),
         *   onBoot(positionInches), onMark(index, {start, end}), onDraw(kind, start, end)
         */
        constructor(stage, options) {
            this.options = options;
            this.svg = make('svg', { class: 'vessel-svg', role: 'img' }, stage);
            this.tip = Object.assign(document.createElement('div'), { className: 'scan-plan-tip', hidden: true });
            this.readout = Object.assign(document.createElement('div'), { className: 'scan-plan-readout' });
            stage.append(this.tip);
            stage.after(this.readout);
            this.scene = null;
            this.view = null;
            this.selected = null;
            this.drawKind = null;
            this.bind();
        }

        // ── the scene ──
        setScene(scene, colours) {
            const first = !this.scene;
            this.scene = scene;
            this.meta = scene.meta;
            this.colours = colours;
            this.px = scene.meta.px_per_unit;
            const width = scene.x_max - scene.x_min, height = scene.y_max - scene.y_min;
            this.fit = [scene.x_min, scene.y_min, width, height];
            this.svg.style.aspectRatio = `${width} / ${height}`;
            if (first || !this.view) this.view = null;
            else this.view[3] = this.view[2] * height / width;   // keep the zoom at the new shape
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

        colour(name) {
            return name ? (this.colours[name] || name) : 'none';
        }

        pts(points) {
            return points.map(([x, y]) => `${x},${y}`).join(' ');
        }

        draw() {
            this.svg.replaceChildren();
            this.groups = {};
            let group = null, groupItem;
            for (const shape of this.scene.shapes) {
                const item = shape.item || '';
                if (!group || item !== groupItem) {
                    group = make('g', item ? { 'data-item': item, class: `item-${item.split(':')[0]}` } : {}, this.svg);
                    groupItem = item;
                    if (item) (this.groups[item] ||= []).push(group);
                }
                this.shape(shape, group);
            }
            if (this.options.mode === 'coverage') this.markHandles();
            this.overlay = make('g', { class: 'vessel-overlay' }, this.svg);
            if (this.selected) this.select(this.selected);
        }

        shape(s, parent) {
            const width = s.width || 0;
            const stroke = s.stroke && width
                ? { stroke: this.colour(s.stroke), 'stroke-width': width, 'vector-effect': 'non-scaling-stroke' }
                : { stroke: 'none' };
            const dash = s.dashed ? { 'stroke-dasharray': '7 4' } : {};
            switch (s.kind) {
                case 'polygon': {
                    const hit = !s.fill && !(s.stroke && width);   // only there to be clicked
                    return make('polygon', { points: this.pts(s.points), fill: hit ? 'transparent' : this.colour(s.fill),
                                             'stroke-linejoin': 'round', 'data-hit': hit ? '1' : null, ...stroke, ...dash }, parent);
                }
                case 'line':
                    return make('polyline', { points: this.pts(s.points), fill: 'none', 'stroke-linecap': 'butt', ...stroke }, parent);
                case 'dashed':
                    return make('polyline', { points: this.pts(s.points), fill: 'none', 'stroke-dasharray': '14 4', ...stroke }, parent);
                case 'circle':
                    return make('circle', { cx: s.at[0], cy: s.at[1], r: s.radius, fill: this.colour(s.fill), ...stroke, ...dash }, parent);
                case 'text': {
                    const anchor = s.anchor || 'mm';
                    const text = make('text', {
                        x: s.at[0], y: s.at[1], 'font-size': s.size / this.px, 'font-family': 'Arial, sans-serif',
                        'font-weight': s.bold ? 'bold' : null, 'text-anchor': ANCHOR[anchor[0]] || 'middle',
                        'dominant-baseline': BASELINE[anchor[1]] || 'central', fill: this.colour(s.colour || 'text'),
                        ...(s.halo ? { stroke: '#fff', 'stroke-width': 3 / this.px, 'paint-order': 'stroke', 'stroke-linejoin': 'round' } : {}),
                    }, parent);
                    text.textContent = s.text;
                    return text;
                }
            }
            return null;
        }

        // ── coordinates ──
        screen(s, r) {
            return this.meta.horizontal ? [s, -r] : [r, -s];
        }

        toScreen(event) {
            const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(this.svg.getScreenCTM().inverse());
            return [p.x, p.y];
        }

        toLocal(event) {
            const [x, y] = this.toScreen(event);
            return this.meta.horizontal ? { s: x, r: -y } : { s: -y, r: x };
        }

        unitsPerPixel() {
            return (this.view || this.fit)[2] / this.svg.getBoundingClientRect().width;
        }

        body() {
            return this.meta.segments.filter(seg => seg.kind === 'course' || seg.kind === 'cone');
        }

        /** Inches along the shell from the start tangent line at drawing position s. */
        inches(s) {
            const m = this.meta;
            if (s <= m.tl_start) return 0;
            if (s >= m.tl_end) return m.length;
            for (const seg of m.segments) {
                if (s >= seg.s0 && s <= seg.s1) {
                    if (seg.kind === 'head') break;
                    if (seg.l1 - seg.l0 < 1e-9) return seg.l0;    // a flange, or a cone drawn only
                    return seg.l0 + (seg.l1 - seg.l0) * (s - seg.s0) / (seg.s1 - seg.s0);
                }
            }
            return s < m.tl_start ? 0 : m.length;
        }

        /** Drawing position s of a point `inches` along the shell. */
        sAt(inches) {
            const m = this.meta;
            for (const seg of this.body()) {
                if (inches >= seg.l0 - 1e-9 && inches <= seg.l1 + 1e-9 && seg.l1 - seg.l0 > 1e-9) {
                    return seg.s0 + (seg.s1 - seg.s0) * (inches - seg.l0) / (seg.l1 - seg.l0);
                }
            }
            return inches <= 0 ? m.tl_start : m.tl_end;
        }

        radiusAt(s) {
            for (const seg of this.body()) {
                if (s >= seg.s0 - 1e-6 && s <= seg.s1 + 1e-6) {
                    return seg.s1 - seg.s0 < 1e-9 ? seg.r0 : seg.r0 + (seg.r1 - seg.r0) * (s - seg.s0) / (seg.s1 - seg.s0);
                }
            }
            return this.meta.max_radius;
        }

        /** Course ends along the shell (inches): what a drag snaps onto. */
        magnets() {
            const ends = new Set([0, this.meta.length]);
            for (const seg of this.body()) { ends.add(seg.l0); ends.add(seg.l1); }
            return [...ends];
        }

        /** A dragged position (inches) snapped: onto a nearby course end, else to 1" (6" with Shift); Alt: free. */
        snap(inches, event, magnets = true) {
            if (event.altKey) return inches;
            if (magnets) {
                const reach = MAGNET_PX * this.unitsPerPixel();
                const s = this.sAt(inches);
                for (const end of this.magnets()) {
                    if (Math.abs(this.sAt(end) - s) <= reach) return end;
                }
            }
            const step = event.shiftKey ? 6 : 1;
            return Math.round(inches / step) * step;
        }

        // ── selection ──
        select(item) {
            this.svg.querySelectorAll('g.is-selected').forEach(g => g.classList.remove('is-selected'));
            this.selected = item;
            (this.groups?.[item] || []).forEach(g => g.classList.add('is-selected'));
        }

        // ── coverage boxes and bands: grab strips over their ends and edges ──
        markHandles() {
            const handles = make('g', { class: 'vessel-handles' }, this.svg);
            const r = this.meta.max_radius + 8;
            const w = END_PX * this.unitsPerPixelSafe();
            for (const mark of this.meta.marks) {
                const lo = Math.min(mark.s0, mark.s1), hi = Math.max(mark.s0, mark.s1);
                const rect = (s0, s1, r0, r1, part, cls) => {
                    const corners = [this.screen(s0, r0), this.screen(s1, r0), this.screen(s1, r1), this.screen(s0, r1)];
                    make('polygon', { points: this.pts(corners), fill: 'transparent', class: cls,
                                      'data-mark': mark.index, 'data-part': part, 'data-item': `mark:${mark.index}` }, handles);
                };
                if (mark.kind === 'box') {   // the box's long edges move it; inside stays clickable
                    rect(lo, hi, r - w, r + w, 'body', 'handle-move');
                    rect(lo, hi, -r - w, -r + w, 'body', 'handle-move');
                } else {
                    const mid = (lo + hi) / 2;
                    const rr = this.radiusAt(mid) * 0.95;
                    rect(lo + w, hi - w, -rr, rr, 'body', 'handle-move');
                }
                const ends = this.meta.horizontal ? 'handle-end' : 'handle-end handle-end-v';
                rect(lo - w, lo + w, -r, r, lo === mark.s0 ? 'start' : 'end', ends);
                rect(hi - w, hi + w, -r, r, hi === mark.s1 ? 'end' : 'start', ends);
            }
        }

        unitsPerPixelSafe() {
            const width = this.svg.getBoundingClientRect().width;
            return width ? (this.view || this.fit)[2] / width : 1 / this.px;
        }

        // ── pointer ──
        bind() {
            const svg = this.svg;
            svg.addEventListener('pointerdown', event => {
                if (event.button !== 0 || !this.scene) return;
                const target = event.target;
                this.press = { clientX: event.clientX, clientY: event.clientY, start: this.toLocal(event), moved: false,
                               target, item: target.closest('[data-item]')?.dataset.item || null,
                               view: [...(this.view || this.fit)] };
                this.press.drag = this.dragFor(target, this.press);
                svg.setPointerCapture(event.pointerId);
            });
            svg.addEventListener('pointermove', event => {
                if (!this.scene) return;
                if (!this.press) { this.hover(event); return; }
                const press = this.press;
                if (!press.moved && Math.hypot(event.clientX - press.clientX, event.clientY - press.clientY) < CLICK_PX) return;
                press.moved = true;
                if (press.drag) this.moveDrag(press.drag, event);
                else this.pan(event);
            });
            const end = event => {
                const press = this.press;
                if (!press) return;
                this.press = null;
                if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
                svg.classList.remove('is-dragging', 'is-panning');
                this.overlay?.replaceChildren();
                this.tip.hidden = true;
                if (event.type !== 'pointerup') { this.cancelPreview(); return; }
                if (!press.moved) {
                    if (this.drawKind) { this.drawKind = null; this.options.onDrawCancel?.(); }
                    else if (press.item) this.options.onClick?.(press.item);
                    return;
                }
                if (press.drag?.result) this.finish(press.drag);
                else this.cancelPreview();
            };
            svg.addEventListener('pointerup', end);
            svg.addEventListener('pointercancel', end);
            svg.addEventListener('pointerleave', () => { if (!this.press) this.readout.textContent = ''; });
            svg.addEventListener('dblclick', () => this.resetView());
            svg.addEventListener('wheel', event => {
                if (!this.scene) return;
                event.preventDefault();
                const [px, py] = this.toScreen(event);
                const [x, y, w, h] = this.view || this.fit;
                const factor = Math.exp(event.deltaY * 0.0015);
                const width = Math.min(Math.max(w * factor, this.fit[2] / 12), this.fit[2] * 2);
                const f = width / w;
                this.view = [px - (px - x) * f, py - (py - y) * f, width, h * f];
                this.applyView();
            }, { passive: false });
            document.addEventListener('keydown', event => {
                if (event.key === 'Escape' && this.press) {
                    this.press = null;
                    this.svg.classList.remove('is-dragging', 'is-panning');
                    this.overlay?.replaceChildren();
                    this.tip.hidden = true;
                    this.cancelPreview();
                }
            });
        }

        pan(event) {
            this.svg.classList.add('is-panning');
            const scale = this.unitsPerPixel();
            const [x, y, w, h] = this.press.view;
            this.view = [x - (event.clientX - this.press.clientX) * scale, y - (event.clientY - this.press.clientY) * scale, w, h];
            this.applyView();
        }

        hover(event) {
            const { s } = this.toLocal(event);
            const m = this.meta;
            if (s < m.tl_start || s > m.tl_end) { this.readout.textContent = ''; return; }
            const from = m.horizontal ? 'left' : 'bottom';
            this.readout.textContent = `Cursor: ${this.options.format(this.inches(s))} from the ${from} tangent line`;
        }

        // ── drags ──
        /** What pressing on `target` would drag, or null (then the press pans or clicks). */
        dragFor(target, press) {
            if (this.drawKind) return { kind: 'draw', mark: this.drawKind };
            if (this.options.mode === 'coverage') {
                const handle = target.closest('[data-mark]');
                if (!handle) return null;
                const mark = this.meta.marks.find(m => m.index === +handle.dataset.mark);
                return mark ? { kind: 'mark', mark, part: handle.dataset.part } : null;
            }
            const item = press.item || '';
            const [type, key] = item.split(':');
            if (type === 'nozzle') {
                const nozzle = this.meta.nozzles.find(n => n.row === +key);
                if (!nozzle || nozzle.fixed) return null;
                return { kind: 'nozzle', nozzle, groups: this.groups[item] || [] };
            }
            if (type === 'seam') {
                const seam = this.meta.seams.find(x => x.number === +key);
                if (!seam || seam.before === null || seam.after === null) return null;   // a head's seam stays
                return { kind: 'seam', seam, groups: this.groups[item] || [] };
            }
            if (type === 'boot' || item === 'part:boot') {
                return { kind: 'boot', groups: [...(this.groups.boot || []), ...(this.groups['part:boot'] || []),
                                                 ...this.bootNozzleGroups()] };
            }
            return null;
        }

        bootNozzleGroups() {
            return this.meta.nozzles.filter(n => n.location === 'boot').flatMap(n => this.groups[`nozzle:${n.row}`] || []);
        }

        translate(groups, ds, dr) {
            const [dx, dy] = this.meta.horizontal ? [ds, -dr] : [dr, -ds];
            groups.forEach(g => g.setAttribute('transform', `translate(${dx} ${dy})`));
        }

        cancelPreview() {
            this.svg.querySelectorAll('g[transform]').forEach(g => g.removeAttribute('transform'));
            this.svg.querySelectorAll('.is-faded').forEach(g => g.classList.remove('is-faded'));
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

        moveDrag(drag, event) {
            this.svg.classList.add('is-dragging');
            const here = this.toLocal(event), start = this.press.start;
            const fmt = this.options.format;
            const m = this.meta;
            if (drag.kind === 'nozzle') {
                const n = drag.nozzle;
                if (n.location === 'shell') {
                    const position = this.snap(this.inches(here.s), event);
                    const s = this.sAt(position);
                    // Dragged well across the centre line: it goes to the other side
                    const flip = n.side !== 0 && here.r * n.side < -0.3 * this.radiusAt(s);
                    this.translate(drag.groups, s - n.s, 0);
                    drag.result = { position, flip };
                    this.showTip(event, [['Position', fmt(position)], ...(flip ? [['Side', 'to the other side']] : [])]);
                } else if (n.location === 'boot') {
                    const b = m.boot;
                    const r = Math.min(b.top, Math.max(b.tl, n.r + (here.r - start.r)));
                    const position = this.snap((b.top - r) / b.scale, event, false);
                    this.translate(drag.groups, 0, (b.top - position * b.scale) - n.r);
                    drag.result = { position: Math.max(0, position) };
                    this.showTip(event, [['Down the boot', fmt(Math.max(0, position))]]);
                } else {   // a head's nozzle: sideways off the centre line
                    const offset = this.snap((n.r + (here.r - start.r)) / m.scale, event, false);
                    this.translate(drag.groups, 0, offset * m.scale - n.r);
                    drag.result = { position: offset };
                    this.showTip(event, [['Off the centre line', fmt(offset)]]);
                }
            } else if (drag.kind === 'seam') {
                const seam = drag.seam;
                const before = this.body().find(seg => seg.index === seam.before);
                const after = this.body().find(seg => seg.index === seam.after);
                const was = this.inches(seam.s);
                let at = this.snap(this.inches(here.s), event, false);
                at = Math.min(Math.max(at, before.l0 + 1), after.l1 - 1);   // each course keeps an inch
                const delta = at - was;
                this.translate(drag.groups, this.sAt(at) - seam.s, 0);
                drag.result = { delta };
                this.showTip(event, [['Seam at', fmt(at)], ['Course before', fmt(before.l1 - before.l0 + delta)],
                                     ['Course after', fmt(after.l1 - after.l0 - delta)]]);
            } else if (drag.kind === 'boot') {
                const position = this.snap(this.inches(here.s), event);
                this.translate(drag.groups, this.sAt(position) - m.boot.s, 0);
                drag.result = { position };
                this.showTip(event, [['Boot centre', fmt(position)]]);
            } else if (drag.kind === 'mark' || drag.kind === 'draw') {
                this.rangeDrag(drag, here, start, event);
            }
        }

        rangeDrag(drag, here, start, event) {
            const fmt = this.options.format;
            let a, b;
            if (drag.kind === 'draw') {
                a = this.snap(this.inches(start.s), event);
                b = this.snap(this.inches(here.s), event);
            } else {
                const mark = drag.mark;
                const s0 = this.inches(mark.s0), s1 = this.inches(mark.s1);
                const shift = this.inches(here.s) - this.inches(start.s);
                if (drag.part === 'body') {
                    const width = s1 - s0;
                    a = this.snap(Math.min(Math.max(s0 + shift, 0), this.meta.length - Math.max(width, 0)), event);
                    b = a + width;
                } else if (drag.part === 'start') {
                    a = this.snap(this.inches(here.s), event); b = s1;
                } else {
                    a = s0; b = this.snap(this.inches(here.s), event);
                }
                (this.groups[`mark:${mark.index}`] || []).forEach(g => g.classList.add('is-faded'));
            }
            const lo = Math.max(0, Math.min(a, b)), hi = Math.min(this.meta.length, Math.max(a, b));
            const r = this.meta.max_radius + 8;
            const s0 = this.sAt(lo), s1 = this.sAt(hi);
            const corners = [this.screen(s0, r), this.screen(s1, r), this.screen(s1, -r), this.screen(s0, -r)];
            this.overlay.replaceChildren();
            make('polygon', { points: this.pts(corners), class: 'vessel-range-preview', 'vector-effect': 'non-scaling-stroke' }, this.overlay);
            drag.result = hi - lo >= 1 ? { start: lo, end: hi } : null;
            this.showTip(event, [['From', fmt(lo)], ['To', fmt(hi)]]);
        }

        finish(drag) {
            const o = this.options;
            if (drag.kind === 'nozzle') o.onNozzle?.(drag.nozzle.row, drag.result);
            else if (drag.kind === 'seam') o.onSeam?.(drag.seam, drag.result.delta);
            else if (drag.kind === 'boot') o.onBoot?.(drag.result.position);
            else if (drag.kind === 'mark') o.onMark?.(drag.mark.index, drag.result);
            else if (drag.kind === 'draw') { this.drawKind = null; o.onDraw?.(drag.mark, drag.result.start, drag.result.end); }
        }
    }

    window.VesselView = VesselView;
})();
