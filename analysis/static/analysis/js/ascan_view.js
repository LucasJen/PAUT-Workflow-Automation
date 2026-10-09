// A-scan of the line under the beam cursor, on a 2D canvas: amplitude (% of full screen height,
// soft gain applied, clipped at the top like the instrument) against true depth or sound path along
// the beam. Gates come from the server's readings (where they really were placed, after synced gates
// moved them) and are drawn as bars at their thresholds with marks at the crossing and the peak.

window.AScanView = (function () {
    const GATE_COLOURS = { I: '#facc15', A: '#ef4444', B: '#22c55e' };

    class AScanView {
        /** options: {format(m, short), unitLength(), onHover(text)} */
        constructor(stage, options) {
            this.options = options;
            this.canvas = Object.assign(document.createElement('canvas'), { className: 'analysis-ascan' });
            stage.append(this.canvas);
            this.gain = 1;
            this.axis = 'depth';     // depth (true depth) or path (sound path)
            this.canvas.addEventListener('pointermove', e => this.hover(e));
            this.canvas.addEventListener('pointerleave', () => this.options.onHover?.(null));
            new ResizeObserver(() => this.draw()).observe(stage);
        }

        /** values: Float32Array percent of one line; ray: its ray (SI); period: s per sample; gates: from the readings */
        set({ values, ray, gates, period }) {
            if (period !== undefined) this.period = period;
            if (values !== undefined) this.values = values;
            if (ray !== undefined) this.ray = ray;
            if (gates !== undefined) this.gates = gates;
            this.draw();
        }

        setGain(db) { this.gain = Math.pow(10, db / 20); this.draw(); }
        setAxis(axis) { this.axis = axis; this.draw(); }

        /** Horizontal position (m) of a sample index / a time along this beam. */
        along(sample) {
            const sp = this.ray.sp_start + sample * this.ray.sp_step;
            return this.axis === 'depth' ? sp * this.ray.dz : sp;
        }

        timeToAlong(t) {
            // sp_start = v * t0 / 2 and sp_step = v * period / 2: sound path is linear in time
            const velocityHalf = this.ray.sp_step / this.period;
            const sp = t * velocityHalf;
            return this.axis === 'depth' ? sp * this.ray.dz : sp;
        }

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
            const x0 = this.along(-0.5), x1 = this.along(this.values.length - 0.5);
            return {
                ratio, left, bottom, top, right, w, h, x0, x1,
                sx: x => left + (x - x0) / (x1 - x0) * (w - left - right),
                sy: p => h - bottom - Math.min(p, 100) / 100 * (h - bottom - top),
                fromX: px => x0 + (px - left) / (w - left - right) * (x1 - x0),
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
            // Grid: 20 % lines and the length axis
            ctx.strokeStyle = 'rgba(148,163,184,0.18)';
            ctx.fillStyle = '#94a3b8';
            ctx.lineWidth = ratio;
            for (let p = 0; p <= 100; p += 20) {
                const y = f.sy(p);
                ctx.beginPath(); ctx.moveTo(f.left, y); ctx.lineTo(w - f.right, y); ctx.stroke();
                ctx.fillText(`${p}`, 6 * ratio, y + 4 * ratio);
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
            // Gates: a bar at the threshold from start to end, crossing (|) and peak (^) marks
            for (const [letter, gate] of Object.entries(this.gates || {})) {
                if (!gate.found || gate.start === null) continue;
                const colour = GATE_COLOURS[letter] || '#e2e8f0';
                ctx.strokeStyle = colour;
                ctx.fillStyle = colour;
                ctx.lineWidth = 2 * ratio;
                const y = f.sy(gate.threshold);
                const a = Math.max(f.left, f.sx(this.timeToAlong(gate.start))), b = Math.min(w - f.right, f.sx(this.timeToAlong(gate.end)));
                if (b > a) {
                    ctx.beginPath(); ctx.moveTo(a, y); ctx.lineTo(b, y); ctx.stroke();
                    ctx.fillText(letter, a + 3 * ratio, y - 4 * ratio);
                }
                if (gate.crossing_time !== null) {
                    const x = f.sx(this.timeToAlong(gate.crossing_time));
                    ctx.beginPath(); ctx.moveTo(x, y - 6 * ratio); ctx.lineTo(x, y + 6 * ratio); ctx.stroke();
                }
                if (gate.peak_time !== null && gate.amplitude !== null) {
                    const x = f.sx(this.timeToAlong(gate.peak_time)), py = f.sy(gate.amplitude);   // the server applied the gain
                    ctx.beginPath(); ctx.moveTo(x - 5 * ratio, py - 8 * ratio); ctx.lineTo(x, py - 2 * ratio);
                    ctx.lineTo(x + 5 * ratio, py - 8 * ratio); ctx.stroke();
                }
            }
            // The trace
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
        }

        hover(e) {
            if (!this.values || !this.ray) return;
            const box = this.canvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            const f = this.frame();
            const x = f.fromX((e.clientX - box.left) * ratio);
            const sample = Math.round((x / (this.axis === 'depth' ? this.ray.dz || 1 : 1) - this.ray.sp_start) / this.ray.sp_step);
            const value = this.values[Math.max(0, Math.min(this.values.length - 1, sample))];
            this.options.onHover?.(`${this.axis === 'depth' ? 'Depth' : 'Sound path'} ${this.options.format(x)} · ${value < 0 ? 'no data' : (value * this.gain).toFixed(1) + ' %'}`);
        }
    }

    return AScanView;
})();
