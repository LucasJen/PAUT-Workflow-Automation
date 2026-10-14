// A-scan of the line under the beam cursor, on a 2D canvas: amplitude (% of full screen height,
// soft gain applied, clipped at the top like the instrument) against true depth or sound path along
// the beam. Gates come from the server's readings (where they really were placed, after synced gates
// moved them) and are drawn as bars at their thresholds with marks at the crossing and the peak.
//
// A floating gate's bar sits at its height on this A-scan, with the band it may float in shaded.
// Editing: drag a gate's bar to move it (and up / down for its threshold), its ends to change its
// start or width. Reference (red) and measure (green) ultrasound cursors: click to put the reference
// there, Shift+click the measure; drag either line. Cursors are kept as true depth (m).
// Scroll to zoom along the axis at the pointer, right-drag to pan, double-click to see it all; the
// zoom bars (bottom: along the beam; side: the amplitude) zoom and move each axis on its own.

window.AScanView = (function () {
    const GATE_COLOURS = { I: '#facc15', A: '#ef4444', B: '#22c55e' };
    const CURSOR_COLOURS = { ref: '#f87171', meas: '#4ade80' };
    const GRAB = 6;   // px
    const MAX_ZOOM = 200;   // times the whole A-scan

    class AScanView {
        /** options: {format(m, short), unitLength(), onHover(text), onGateDragStart(letter),
         *  onGateDrag(letter, {part, dt, threshold}), onGateDragEnd(), onCursor(which, depth)} */
        constructor(stage, options) {
            this.options = options;
            this.canvas = Object.assign(document.createElement('canvas'), { className: 'analysis-ascan' });
            stage.append(this.canvas);
            this.gain = 1;
            this.axis = 'depth';     // depth (true depth) or path (sound path)
            this.cursors = { ref: null, meas: null };
            this.zoom = null;   // [from, to] along the axis (m), or null for all of it
            this.amp = [0, 100];   // the amplitudes shown, bottom to top (%)
            this.bind();
            new ResizeObserver(() => this.draw()).observe(stage);
        }

        /** values: Float32Array percent of one line; ray: its ray (SI); period: s per sample;
         *  gates: from the readings; cursors: {ref, meas} true depths (m) */
        set({ values, ray, gates, period, cursors }) {
            if (period !== undefined) this.period = period;
            if (values !== undefined) this.values = values;
            if (ray !== undefined) this.ray = ray;
            if (gates !== undefined) this.gates = gates;
            if (cursors !== undefined) this.cursors = cursors;
            this.draw();
        }

        setGain(db) { this.gain = Math.pow(10, db / 20); this.draw(); }
        setAxis(axis) { this.axis = axis; this.draw(); }
        /** The part's thickness (m) for the leg lines (T, 2T, ... in depth), or null for none. */
        setLegs(thickness) { this.legs = thickness || null; this.draw(); }

        // ── positions along the axis ──
        along(sample) {
            const sp = this.ray.sp_start + sample * this.ray.sp_step;
            return this.axis === 'depth' ? sp * this.ray.dz : sp;
        }
        halfVelocity() { return this.ray.sp_step / this.period; }   // sound path per second of round trip
        timeToAlong(t) {
            const sp = t * this.halfVelocity();
            return this.axis === 'depth' ? sp * this.ray.dz : sp;
        }
        alongToTime(x) {
            const sp = this.axis === 'depth' ? x / (this.ray.dz || 1) : x;
            return sp / this.halfVelocity();
        }
        depthToAlong(d) { return this.axis === 'depth' ? d : d / (this.ray.dz || 1); }
        alongToDepth(x) { return this.axis === 'depth' ? x : x * this.ray.dz; }

        resize() {
            const ratio = window.devicePixelRatio || 1;
            const c = this.canvas;
            const w = Math.max(1, Math.round(c.clientWidth * ratio)), h = Math.max(1, Math.round(c.clientHeight * ratio));
            if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
            return ratio;
        }

        frame() {
            const ratio = window.devicePixelRatio || 1;
            const left = 40 * ratio, bottom = 20 * ratio, top = 8 * ratio, right = 10 * ratio;
            const w = this.canvas.width, h = this.canvas.height;
            const full0 = this.along(-0.5), full1 = this.along(this.values.length - 0.5);
            const [x0, x1] = this.zoom || [full0, full1];
            const [lo, hi] = this.amp;
            return {
                ratio, left, bottom, top, right, w, h, x0, x1, full0, full1, lo, hi,
                sx: x => left + (x - x0) / (x1 - x0) * (w - left - right),
                sy: p => h - bottom - (Math.min(Math.max(p, lo), hi) - lo) / (hi - lo) * (h - bottom - top),
                fromX: px => x0 + (px - left) / (w - left - right) * (x1 - x0),
                fromY: py => lo + (h - bottom - py) / (h - bottom - top) * (hi - lo),
            };
        }

        draw() {
            const ratio = this.resize();
            const ctx = this.canvas.getContext('2d');
            const w = this.canvas.width, h = this.canvas.height;
            ctx.fillStyle = '#0b0d11';
            ctx.fillRect(0, 0, w, h);
            if (!this.values || !this.ray) return;
            const f = this.frame();
            ctx.font = `${11 * ratio}px Inter, Arial, sans-serif`;
            ctx.strokeStyle = 'rgba(148,163,184,0.18)';
            ctx.fillStyle = '#94a3b8';
            ctx.lineWidth = ratio;
            const pStep = [0.5, 1, 2, 2.5, 5, 10, 20].find(s => s >= (f.hi - f.lo) / 5.01) || 20;
            for (let p = Math.ceil(f.lo / pStep - 1e-9) * pStep; p <= f.hi + 1e-9; p += pStep) {
                const y = f.sy(p);
                ctx.beginPath(); ctx.moveTo(f.left, y); ctx.lineTo(w - f.right, y); ctx.stroke();
                ctx.fillText(`${+p.toFixed(1)}`, 6 * ratio, y + 4 * ratio);
            }
            const unit = this.options.unitLength();
            const span = (f.x1 - f.x0) / unit;
            const target = span / Math.max(2, (w - f.left) / (70 * ratio));
            const mag = Math.pow(10, Math.floor(Math.log10(target)));
            const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= target) * unit;
            for (let x = Math.ceil(f.x0 / step) * step; x <= f.x1; x += step) {
                const px = f.sx(x);
                ctx.beginPath(); ctx.moveTo(px, h - f.bottom); ctx.lineTo(px, h - f.bottom + 5 * ratio); ctx.stroke();
                ctx.fillText(this.options.format(x, true), px + 2 * ratio, h - 5 * ratio);
            }
            // The legs: dashed lines where the beam reaches each multiple of the thickness (along this axis)
            if (this.legs && this.ray) {
                ctx.save();
                ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.fillStyle = 'rgba(255,255,255,0.75)';
                ctx.setLineDash([6 * ratio, 5 * ratio]);
                ctx.lineWidth = ratio;
                for (let k = 1; k < 50; k++) {
                    const along = this.depthToAlong(k * this.legs);
                    if (along > f.x1) break;
                    if (along < f.x0) continue;
                    const x = f.sx(along);
                    ctx.beginPath(); ctx.moveTo(x, f.top); ctx.lineTo(x, h - f.bottom); ctx.stroke();
                    ctx.fillText(k === 1 ? 'T' : `${k}T`, x + 3 * ratio, h - f.bottom - 6 * ratio);
                }
                ctx.restore();
            }
            // Cursors: full-height lines with their value at the top
            for (const which of ['ref', 'meas']) {
                const depth = this.cursors[which];
                if (depth === null || depth === undefined) continue;
                const x = f.sx(this.depthToAlong(depth));
                if (x < f.left || x > w - f.right) continue;
                ctx.strokeStyle = ctx.fillStyle = CURSOR_COLOURS[which];
                ctx.lineWidth = ratio;
                ctx.beginPath(); ctx.moveTo(x, f.top); ctx.lineTo(x, h - f.bottom); ctx.stroke();
                ctx.fillText(this.options.format(this.depthToAlong(depth), 'value'), x + 3 * ratio, f.top + 10 * ratio);
            }
            this.gateBars = [];
            for (const [letter, gate] of Object.entries(this.gates || {})) {
                if (!gate.found || gate.start === null) continue;
                const colour = GATE_COLOURS[letter] || '#e2e8f0';
                ctx.strokeStyle = colour;
                ctx.fillStyle = colour;
                ctx.lineWidth = 2 * ratio;
                // A floating gate: drawn at its height on this A-scan, over a faint band of the heights it
                // may float to; dashed at the bottom of the band when the peak is under its floor
                const under = gate.band && (gate.threshold === null || gate.threshold === undefined);
                const y = f.sy(under ? gate.band[0] : gate.threshold);
                const a = f.sx(this.timeToAlong(gate.start)), b = f.sx(this.timeToAlong(gate.end));
                this.gateBars.push({ letter, a, b, y });
                const ca = Math.max(f.left, a), cb = Math.min(w - f.right, b);
                if (cb > ca) {
                    if (gate.band) {
                        const y0 = f.sy(gate.band[0]), y1 = f.sy(gate.band[1]);
                        ctx.save();
                        ctx.globalAlpha = 0.14;
                        ctx.fillRect(ca, Math.min(y0, y1), cb - ca, Math.abs(y0 - y1));
                        ctx.restore();
                    }
                    ctx.save();
                    if (under) ctx.setLineDash([5 * ratio, 4 * ratio]);
                    ctx.beginPath(); ctx.moveTo(ca, y); ctx.lineTo(cb, y); ctx.stroke();
                    ctx.restore();
                    ctx.fillText(letter, ca + 3 * ratio, y - 4 * ratio);
                    for (const end of [a, b]) {   // end ticks: grab them to change the start / width
                        if (end >= f.left && end <= w - f.right) {
                            ctx.beginPath(); ctx.moveTo(end, y - 4 * ratio); ctx.lineTo(end, y + 4 * ratio); ctx.stroke();
                        }
                    }
                }
                if (gate.crossing_time !== null) {
                    const x = f.sx(this.timeToAlong(gate.crossing_time));
                    ctx.beginPath(); ctx.moveTo(x, y - 7 * ratio); ctx.lineTo(x, y + 7 * ratio); ctx.stroke();
                }
                if (gate.peak_time !== null && gate.amplitude !== null && gate.crossing_time !== null) {
                    const x = f.sx(this.timeToAlong(gate.peak_time)), py = f.sy(gate.amplitude);   // the server applied the gain
                    if (x >= f.left && x <= w - f.right) {
                        ctx.beginPath(); ctx.moveTo(x - 5 * ratio, py - 8 * ratio); ctx.lineTo(x, py - 2 * ratio);
                        ctx.lineTo(x + 5 * ratio, py - 8 * ratio); ctx.stroke();
                        ctx.fillText(`${gate.amplitude.toFixed(1)}%`, x + 7 * ratio, Math.max(f.top + 10 * ratio, py - 6 * ratio));
                    }
                }
            }
            ctx.save();
            ctx.beginPath();
            ctx.rect(f.left, 0, w - f.left - f.right, h);
            ctx.clip();
            ctx.strokeStyle = '#fde047';
            ctx.lineWidth = 1.2 * ratio;
            ctx.beginPath();
            const n = this.values.length;
            for (let i = 0; i < n; i++) {
                const v = this.values[i];
                const x = f.sx(this.along(i)), y = f.sy(v < 0 ? 0 : v * this.gain);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.restore();
        }

        resetZoom() { this.zoom = null; this.amp = [0, 100]; this.draw(); }
        maxZoom() { return MAX_ZOOM; }

        /** The full and shown stretch of an axis, for the zoom bars: 'x' along the beam (m), 'y' the
         *  amplitude (%, highest at the top: flip). */
        axisRange(axis) {
            if (axis === 'y') return { full: [0, 100], shown: [...this.amp], flip: true };
            if (!this.values || !this.ray) return null;
            const f = this.frame();
            return { full: [f.full0, f.full1], shown: [f.x0, f.x1] };
        }

        setAxisRange(axis, [a, b]) {
            if (axis === 'y') {
                this.amp = [Math.max(0, a), Math.min(100, b)];
            } else {
                if (!this.values || !this.ray) return;
                const f = this.frame();
                this.zoom = b - a >= f.full1 - f.full0 - 1e-12 ? null : [Math.max(f.full0, a), Math.min(f.full1, b)];
            }
            this.draw();
        }

        // ── pointer ──
        point(e) {
            const box = this.canvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            return [(e.clientX - box.left) * ratio, (e.clientY - box.top) * ratio];
        }

        /** What a press at (px, py) grabs: a cursor line, a gate end, a gate bar, or nothing. */
        grab(px, py, f) {
            const r = f.ratio * GRAB;
            for (const which of ['meas', 'ref']) {
                const d = this.cursors[which];
                if (d !== null && d !== undefined && Math.abs(f.sx(this.depthToAlong(d)) - px) <= r) return { kind: 'cursor', which };
            }
            for (const bar of this.gateBars || []) {
                if (Math.abs(py - bar.y) > r * 1.5) continue;
                if (Math.abs(px - bar.a) <= r) return { kind: 'gate', letter: bar.letter, part: 'start' };
                if (Math.abs(px - bar.b) <= r) return { kind: 'gate', letter: bar.letter, part: 'end' };
                if (px > bar.a && px < bar.b) return { kind: 'gate', letter: bar.letter, part: 'move' };
            }
            return null;
        }

        bind() {
            const c = this.canvas;
            let drag = null;
            c.addEventListener('contextmenu', e => e.preventDefault());
            c.addEventListener('dblclick', () => this.resetZoom());
            c.addEventListener('wheel', e => {
                if (!this.values || !this.ray) return;
                e.preventDefault();
                const f = this.frame();
                const [px] = this.point(e);
                const at = f.fromX(px);
                const k = Math.exp(e.deltaY * 0.0015);
                const span = Math.min(f.full1 - f.full0, Math.max((f.x1 - f.x0) * k, (f.full1 - f.full0) / MAX_ZOOM));
                let a = at - (at - f.x0) / (f.x1 - f.x0) * span;
                a = Math.max(f.full0, Math.min(f.full1 - span, a));
                this.zoom = span >= f.full1 - f.full0 - 1e-12 ? null : [a, a + span];
                this.draw();
            }, { passive: false });
            c.addEventListener('pointerdown', e => {
                if ((e.button === 2 || e.button === 1) && this.values && this.zoom) {
                    c.setPointerCapture(e.pointerId);
                    drag = { kind: 'pan', x: e.clientX, zoom: [...this.zoom] };
                    return;
                }
                if (e.button !== 0 || !this.values || !this.ray) return;
                const f = this.frame();
                const [px, py] = this.point(e);
                const hit = this.grab(px, py, f);
                c.setPointerCapture(e.pointerId);
                if (hit?.kind === 'gate') {
                    drag = { ...hit, x: f.fromX(px) };
                    this.options.onGateDragStart?.(hit.letter);
                } else if (hit?.kind === 'cursor') {
                    drag = hit;
                } else {
                    const which = e.shiftKey ? 'meas' : 'ref';
                    this.options.onCursor?.(which, this.alongToDepth(f.fromX(px)));
                    drag = { kind: 'cursor', which };
                }
            });
            c.addEventListener('pointermove', e => {
                if (!this.values || !this.ray) return;
                const f = this.frame();
                const [px, py] = this.point(e);
                if (!drag) {
                    const hit = this.grab(px, py, f);
                    c.style.cursor = !hit ? 'crosshair' : hit.kind === 'cursor' || hit.part !== 'move' ? 'ew-resize' : 'move';
                    this.hover(px, f);
                    return;
                }
                if (drag.kind === 'pan') {
                    const box = c.getBoundingClientRect();
                    const span = drag.zoom[1] - drag.zoom[0];
                    const shift = -(e.clientX - drag.x) / Math.max(1, box.width - 50) * span;
                    const lo = Math.max(f.full0, Math.min(f.full1 - span, drag.zoom[0] + shift));
                    this.zoom = [lo, lo + span];
                    this.draw();
                    return;
                }
                if (drag.kind === 'cursor') {
                    this.options.onCursor?.(drag.which, this.alongToDepth(f.fromX(px)));
                } else {
                    const dt = this.alongToTime(f.fromX(px)) - this.alongToTime(drag.x);
                    const threshold = drag.part === 'move' ? Math.max(0, Math.min(100, f.fromY(py))) : undefined;
                    this.options.onGateDrag?.(drag.letter, { part: drag.part, dt, threshold });
                }
            });
            const end = () => {
                if (drag?.kind === 'gate') this.options.onGateDragEnd?.();
                drag = null;
            };
            c.addEventListener('pointerup', end);
            c.addEventListener('pointercancel', end);
            c.addEventListener('pointerleave', () => { if (!drag) this.options.onHover?.(null); });
        }

        hover(px, f) {
            const x = f.fromX(px);
            const sample = Math.round((x / (this.axis === 'depth' ? this.ray.dz || 1 : 1) - this.ray.sp_start) / this.ray.sp_step);
            const value = this.values[Math.max(0, Math.min(this.values.length - 1, sample))];
            this.options.onHover?.(`${this.axis === 'depth' ? 'Depth' : 'Sound path'} ${this.options.format(x)} · ${value < 0 ? 'no data' : (value * this.gain).toFixed(1) + ' %'}`);
        }
    }

    return AScanView;
})();
