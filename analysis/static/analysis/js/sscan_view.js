// S-scan (sectorial / linear / raster end view) in true geometry, drawn with WebGL2. Each frame is
// a texture of percent values (lines x samples); every line is drawn along its ray from the
// server (exit point, direction, sound path per sample), so depths and positions are where the
// beam really went. Soft gain and the palette are applied in the shader, so changing them doesn't
// fetch anything. A 2D overlay canvas draws the axes, back-wall / skip lines and the beam cursor.
//
// World coordinates: x = position along the index axis (m), y = depth (m, down). Click or drag
// to move the beam cursor, scroll to zoom at the pointer, right-drag to pan, double-click to fit.
// True geometry keeps one scale both ways (a sectorial fan); stretched fills the panel (a 0 deg
// raster's index x depth end view, e.g. 12 in wide and 0.5 in deep).
// Cursors: reference (red) and measure (green) - depth (U, horizontal lines) and index (I, vertical
// lines). Ctrl+click puts the reference pair at a point, Shift+click the measure pair; drag a line
// to move it.

window.SScanView = (function () {
    const VERTEX = `#version 300 es
in vec2 aPos;
in vec2 aTex;
uniform vec4 uView;   // centre x, centre y, 2 / width, 2 / height (world units)
out vec2 vTex;
void main() {
    vTex = aTex;
    gl_Position = vec4((aPos.x - uView.x) * uView.z, -(aPos.y - uView.y) * uView.w, 0.0, 1.0);
}`;
    const FRAGMENT = `#version 300 es
precision highp float;
in vec2 vTex;
uniform sampler2D uData;
uniform sampler2D uPalette;
uniform float uGain;
out vec4 outColor;
void main() {
    float a = texture(uData, vTex).r;
    if (a < -0.5) { outColor = vec4(0.30, 0.30, 0.32, 1.0); return; }   // no data at this position
    float p = clamp(a * uGain / 100.0, 0.0, 1.0);
    outColor = texture(uPalette, vec2(p * (255.0 / 256.0) + 0.5 / 256.0, 0.5));
}`;

    function compile(gl, type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
        return shader;
    }

    class SScanView {
        /** stage: element to draw in. options: {format(m), onCursor(lateral), onHover(text)} */
        constructor(stage, options) {
            this.options = options;
            this.canvas = Object.assign(document.createElement('canvas'), { className: 'analysis-gl' });
            this.overlay = Object.assign(document.createElement('canvas'), { className: 'analysis-overlay' });
            stage.append(this.canvas, this.overlay);
            this.stage = stage;
            const gl = this.canvas.getContext('webgl2', { antialias: true, preserveDrawingBuffer: true });
            if (!gl) throw new Error('This browser has no WebGL2.');
            this.gl = gl;
            const program = gl.createProgram();
            gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
            gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
            gl.linkProgram(program);
            if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
            this.program = program;
            this.loc = {
                pos: gl.getAttribLocation(program, 'aPos'), tex: gl.getAttribLocation(program, 'aTex'),
                view: gl.getUniformLocation(program, 'uView'), gain: gl.getUniformLocation(program, 'uGain'),
                data: gl.getUniformLocation(program, 'uData'), palette: gl.getUniformLocation(program, 'uPalette'),
            };
            this.buffer = gl.createBuffer();
            this.dataTexture = gl.createTexture();
            this.paletteTexture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, this.paletteTexture);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, AnalysisPalette.amplitude());
            this.filter(gl.LINEAR);
            this.gain = 1;
            this.view = null;       // [cx, cy, width, height] in world units; null = fit
            this.trueGeometry = true;
            this.cursors = { u_ref: null, u_meas: null, i_ref: null, i_meas: null };
            this.lateral = 0;
            this.hasFrame = false;
            this.bind();
            new ResizeObserver(() => this.draw()).observe(stage);
        }

        filter(mode) {
            const gl = this.gl;
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        }

        // ── geometry ──
        /** rays: from the server (SI); samples: per line; thickness: m or null. */
        /** The S-scan mesh of a set of rays: {verts (x, y, s, t per vertex), parallel, bounds}. */
        static mesh(rays, samples) {
            // Lines going the same way (linear / raster) sit side by side; a fan interpolates between rays
            const parallel = rays.every(r => Math.abs(r.dz - rays[0].dz) < 1e-6 && Math.abs(r.dv - rays[0].dv) < 1e-6);
            const lines = rays.length;
            const point = (r, sample) => {
                const sp = r.sp_start + sample * r.sp_step;
                return [r.v0 + r.dv * sp, r.dz * sp];
            };
            const verts = [];
            const quad = (a, b, c, d) => verts.push(...a, ...b, ...c, ...a, ...c, ...d);
            const s0 = -0.5, s1 = samples - 0.5;
            const between = i => {
                const ta = (i + 0.5) / lines, tb = (i + 1.5) / lines;
                const a0 = point(rays[i], s0), a1 = point(rays[i], s1);
                const b0 = point(rays[i + 1], s0), b1 = point(rays[i + 1], s1);
                quad([...a0, 0, ta], [...a1, 1, ta], [...b1, 1, tb], [...b0, 0, tb]);
            };
            if (lines === 1) {
                const [x0, y0] = point(rays[0], s0), [x1, y1] = point(rays[0], s1);
                quad([x0 - 0.0005, y0, 0, 0.5], [x1 - 0.0005, y1, 1, 0.5], [x1 + 0.0005, y1, 1, 0.5], [x0 + 0.0005, y0, 0, 0.5]);
            } else {
                for (let i = 0; i < lines - 1; i++) between(i);
                if (parallel) {   // half a spacing beyond the outer two lines
                    const shift = (q, dx) => [q[0] + dx, q[1]];
                    const first = rays[0], last = rays[lines - 1];
                    const h = (rays[1].v0 - first.v0) / 2;
                    const t0 = 0.5 / lines, t1 = (lines - 0.5) / lines;
                    const f0 = point(first, s0), f1 = point(first, s1), l0 = point(last, s0), l1 = point(last, s1);
                    quad([...shift(f0, -h), 0, t0], [...shift(f1, -h), 1, t0], [...f1, 1, t0], [...f0, 0, t0]);
                    quad([...l0, 0, t1], [...l1, 1, t1], [...shift(l1, h), 1, t1], [...shift(l0, h), 0, t1]);
                }
            }
            let x0 = Infinity, x1 = -Infinity, y0 = 0, y1 = -Infinity;
            for (let i = 0; i < verts.length; i += 4) {
                x0 = Math.min(x0, verts[i]); x1 = Math.max(x1, verts[i]);
                y0 = Math.min(y0, verts[i + 1]); y1 = Math.max(y1, verts[i + 1]);
            }
            return { verts: new Float32Array(verts), parallel, bounds: [x0, y0, x1, y1] };
        }

        /** rays: from the server (SI); samples: per line; thickness: m or null. */
        setGeometry(rays, samples, thickness) {
            this.rays = rays;
            this.samples = samples;
            this.thickness = thickness || null;
            const { verts, parallel, bounds } = SScanView.mesh(rays, samples);
            this.parallel = parallel;
            this.vertexCount = verts.length / 4;
            const gl = this.gl;
            gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
            gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
            this.ownBounds = bounds;
            this.setExtras([]);
            this.view = null;
            this.trueGeometry = !parallel;   // fans in true geometry; side-by-side lines stretched
            this.lateral = Math.min(this.lateral, rays.length - 1);
            this.draw();
        }

        /**
         * Other groups drawn under this one at the same scan position (e.g. a weld's Root and Body
         * groups together): [{rays, samples, values, lines}] - values as for setFrame.
         */
        setExtras(list) {
            const gl = this.gl;
            this.extras = this.extras || [];
            while (this.extras.length < list.length) this.extras.push({ buffer: gl.createBuffer(), texture: gl.createTexture() });
            this.extras.length = list.length;
            let [x0, y0, x1, y1] = this.ownBounds || [0, 0, 1, 1];
            list.forEach((item, i) => {
                const layer = this.extras[i];
                layer.rays = item.rays;
                layer.samples = item.samples;
                const { verts, bounds } = SScanView.mesh(item.rays, item.samples);
                gl.bindBuffer(gl.ARRAY_BUFFER, layer.buffer);
                gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
                layer.count = verts.length / 4;
                gl.bindTexture(gl.TEXTURE_2D, layer.texture);
                gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, item.samples, item.lines, 0, gl.RED, gl.FLOAT, item.values);
                this.filter(gl.LINEAR);
                [x0, y0, x1, y1] = [Math.min(x0, bounds[0]), Math.min(y0, bounds[1]), Math.max(x1, bounds[2]), Math.max(y1, bounds[3])];
            });
            this.bounds = [x0, y0, x1, y1];
            this.draw();
        }

        setTrueGeometry(on) {
            this.trueGeometry = on;
            this.view = null;
            this.draw();
        }

        /** values: Float32Array of percent (lines x samples), -1 where there's no data. */
        setFrame(values, lines, samples) {
            const gl = this.gl;
            gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
            gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, samples, lines, 0, gl.RED, gl.FLOAT, values);
            this.filter(gl.LINEAR);
            this.hasFrame = true;
            this.draw();
        }

        setGain(db) {
            this.gain = Math.pow(10, db / 20);
            this.draw();
        }

        /** An amplitude palette by name (palette.js). */
        setPalette(name) {
            this.paletteName = name;
            const gl = this.gl;
            gl.bindTexture(gl.TEXTURE_2D, this.paletteTexture);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, AnalysisPalette.get('amplitude', name));
            this.draw();
        }

        setCursor(lateral) {
            this.lateral = lateral;
            this.drawOverlay();
        }

        setCursors(cursors) {
            this.cursors = cursors;
            this.drawOverlay();
        }

        /** The weld's outline (index x depth polylines for the first leg, m), or null; drawn in every leg. */
        setWeld(lines, show = true) {
            this.weld = lines && lines.length ? lines : null;
            this.showWeld = show;
            this.drawOverlay();
        }

        /** Moves the weld's centre line across the index (m) - where the weld really is from the probe. */
        setWeldShift(shift) {
            this.weldShift = shift || 0;
            this.drawOverlay();
        }

        // ── view ──
        fitView() {
            const [x0, y0, x1, y1] = this.bounds;
            const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
            const pad = 0.04;
            let width = (x1 - x0) * (1 + 2 * pad), height = (y1 - y0) * (1 + 2 * pad);
            if (!this.trueGeometry) return [(x0 + x1) / 2, (y0 + y1) / 2, width, height];
            if (width / height > w / h) height = width * h / w;   // same scale both ways: true geometry
            else width = height * w / h;
            return [(x0 + x1) / 2, (y0 + y1) / 2, width, height];
        }

        currentView() {
            if (!this.view) return this.fitView();
            if (!this.trueGeometry) return this.view;
            const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
            const [cx, cy, width] = this.view;
            return [cx, cy, width, width * h / w];
        }

        toWorld(event) {
            const box = this.canvas.getBoundingClientRect();
            const [cx, cy, width, height] = this.currentView();
            return [cx + ((event.clientX - box.left) / box.width - 0.5) * width,
                    cy + ((event.clientY - box.top) / box.height - 0.5) * height];
        }

        toScreen(x, y) {
            const [cx, cy, width, height] = this.currentView();
            const w = this.overlay.width, h = this.overlay.height;
            return [((x - cx) / width + 0.5) * w, ((y - cy) / height + 0.5) * h];
        }

        resize() {
            const ratio = window.devicePixelRatio || 1;
            for (const c of [this.canvas, this.overlay]) {
                const w = Math.max(1, Math.round(c.clientWidth * ratio)), h = Math.max(1, Math.round(c.clientHeight * ratio));
                if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
            }
        }

        draw() {
            if (!this.rays) return;
            this.resize();
            const gl = this.gl;
            gl.viewport(0, 0, this.canvas.width, this.canvas.height);
            gl.clearColor(0.06, 0.07, 0.09, 1);
            gl.clear(gl.COLOR_BUFFER_BIT);
            if (this.hasFrame) {
                gl.useProgram(this.program);
                const [cx, cy, width, height] = this.currentView();
                gl.uniform4f(this.loc.view, cx, cy, 2 / width, 2 / height);
                gl.uniform1f(this.loc.gain, this.gain);
                gl.activeTexture(gl.TEXTURE1);
                gl.bindTexture(gl.TEXTURE_2D, this.paletteTexture);
                gl.uniform1i(this.loc.palette, 1);
                const layer = (buffer, texture, count) => {
                    gl.activeTexture(gl.TEXTURE0);
                    gl.bindTexture(gl.TEXTURE_2D, texture);
                    gl.uniform1i(this.loc.data, 0);
                    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
                    gl.enableVertexAttribArray(this.loc.pos);
                    gl.vertexAttribPointer(this.loc.pos, 2, gl.FLOAT, false, 16, 0);
                    gl.enableVertexAttribArray(this.loc.tex);
                    gl.vertexAttribPointer(this.loc.tex, 2, gl.FLOAT, false, 16, 8);
                    gl.drawArrays(gl.TRIANGLES, 0, count);
                };
                for (const extra of this.extras || []) layer(extra.buffer, extra.texture, extra.count);
                layer(this.buffer, this.dataTexture, this.vertexCount);
            }
            this.drawOverlay();
        }

        drawOverlay() {
            if (!this.rays) return;
            const ctx = this.overlay.getContext('2d');
            const ratio = window.devicePixelRatio || 1;
            const w = this.overlay.width, h = this.overlay.height;
            ctx.clearRect(0, 0, w, h);
            const [cx, cy, width, height] = this.currentView();
            ctx.save();
            ctx.font = `${11 * ratio}px Inter, Arial, sans-serif`;
            // Back wall and skips: dashed lines at each thickness
            if (this.thickness) {
                ctx.strokeStyle = 'rgba(255,255,255,0.55)';
                ctx.setLineDash([6 * ratio, 5 * ratio]);
                ctx.lineWidth = ratio;
                for (let k = 1; k * this.thickness < cy + height / 2; k++) {
                    const [, y] = this.toScreen(0, k * this.thickness);
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
                    ctx.fillStyle = 'rgba(255,255,255,0.7)';
                    ctx.fillText(k === 1 ? 'T' : `${k}T`, w - 22 * ratio, y - 3 * ratio);
                }
                ctx.setLineDash([]);
                // The weld outline in each leg: mirrored at the back wall on even legs
                if (this.weld && this.showWeld) {
                    const T = this.thickness;
                    // Only inside the scanned area: the exit points along the top, the last samples round the bottom
                    ctx.save();
                    ctx.beginPath();
                    const edge = (r, sp) => this.toScreen(r.v0 + r.dv * sp, r.dz * sp);
                    // Every group drawn (this one and the others under it)
                    const areas = [{ rays: this.rays, samples: this.samples }, ...(this.extras || [])];
                    for (const area of areas) {
                        area.rays.forEach((r, i) => { const [x, y] = edge(r, r.sp_start); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
                        [...area.rays].reverse().forEach(r => { const [x, y] = edge(r, r.sp_start + area.samples * r.sp_step); ctx.lineTo(x, y); });
                        ctx.closePath();
                    }
                    ctx.clip('nonzero');
                    ctx.strokeStyle = 'rgba(232, 121, 249, 0.9)';
                    ctx.lineWidth = 1.3 * ratio;
                    for (let k = 0; k * T < cy + height / 2; k++) {
                        const fold = y => (k % 2 === 0 ? y + k * T : (k + 1) * T - y);
                        // Each leg's copy only from its own start down: a cap past the surface shows where the beam would
                        // reach it going straight on, and the mirrored copy of the cap the leg before can't close it into an oval
                        ctx.save();
                        const [, top] = this.toScreen(0, k * T);
                        ctx.beginPath(); ctx.rect(0, Math.max(0, top), w, h); ctx.clip();
                        for (const line of this.weld) {
                            ctx.beginPath();
                            line.forEach(([x, y], i) => {
                                const [sx, sy] = this.toScreen(x + (this.weldShift || 0), fold(y));
                                if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
                            });
                            ctx.stroke();
                        }
                        ctx.restore();
                    }
                    ctx.restore();
                }
            }
            // The beam cursor along its ray
            const r = this.rays[this.lateral];
            if (r) {
                const sp0 = r.sp_start, sp1 = r.sp_start + this.samples * r.sp_step;
                const [x0, y0] = this.toScreen(r.v0 + r.dv * sp0, r.dz * sp0);
                const [x1, y1] = this.toScreen(r.v0 + r.dv * sp1, r.dz * sp1);
                ctx.strokeStyle = '#38bdf8';
                ctx.lineWidth = 1.5 * ratio;
                ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
            }
            // The colour scale, top right
            if (this.hasFrame) {
                const bh = Math.min(140 * ratio, h * 0.35);
                AnalysisPalette.legend(ctx, 'amplitude', this.paletteName || 'omnipc', w - 16 * ratio, 8 * ratio, 8 * ratio, bh,
                                       '100%', '0', ratio);
            }
            // Reference / measure cursors: depth (U) across, index (I) up and down
            const colours = { ref: '#f87171', meas: '#4ade80' };
            for (const which of ['ref', 'meas']) {
                ctx.strokeStyle = colours[which];
                ctx.lineWidth = ratio;
                const u = this.cursors[`u_${which}`], i = this.cursors[`i_${which}`];
                if (u !== null && u !== undefined) {
                    const [, y] = this.toScreen(0, u);
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
                }
                if (i !== null && i !== undefined) {
                    const [x] = this.toScreen(i, 0);
                    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
                }
            }
            // Axes: depth down the left, index position along the bottom
            ctx.fillStyle = '#e2e8f0';
            ctx.lineJoin = 'round';
            const label = (text, x, y) => {
                ctx.save(); ctx.strokeStyle = 'rgba(8,10,14,0.9)'; ctx.lineWidth = 3 * ratio;
                ctx.strokeText(text, x, y); ctx.restore(); ctx.fillText(text, x, y);
            };
            ctx.strokeStyle = '#94a3b8';
            ctx.lineWidth = ratio;
            const step = (span, pixels) => {
                const target = span / Math.max(2, pixels / (70 * ratio));
                const mag = Math.pow(10, Math.floor(Math.log10(target)));
                return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= target);
            };
            const unit = this.options.unitLength();
            const xs = step(width / unit, w) * unit, ys = step(height / unit, h) * unit;
            for (let x = Math.ceil((cx - width / 2) / xs) * xs; x <= cx + width / 2; x += xs) {
                const [sx] = this.toScreen(x, 0);
                if (sx < 46 * ratio) continue;
                ctx.beginPath(); ctx.moveTo(sx, h - 18 * ratio); ctx.lineTo(sx, h - 13 * ratio); ctx.stroke();
                label(this.options.format(x, true), sx + 2 * ratio, h - 5 * ratio);
            }
            for (let y = Math.ceil((cy - height / 2) / ys) * ys; y <= cy + height / 2; y += ys) {
                const [, sy] = this.toScreen(0, y);
                if (sy > h - 18 * ratio) continue;
                ctx.beginPath(); ctx.moveTo(40 * ratio, sy); ctx.lineTo(46 * ratio, sy); ctx.stroke();
                label(this.options.format(y, true), 3 * ratio, sy + 4 * ratio);
            }
            ctx.restore();
        }

        // ── pointer ──
        /** The line nearest a world point: the ray it lies along (fan) or the strip it's in. */
        pick([x, y]) {
            let best = 0, bestDistance = Infinity;
            this.rays.forEach((r, i) => {
                let distance;
                if (this.parallel) {
                    distance = Math.abs(x - r.v0);
                } else {
                    const len = Math.hypot(r.dv, r.dz) || 1;
                    const ux = r.dv / len, uy = r.dz / len;
                    const px = x - r.v0, py = y;
                    distance = Math.abs(px * uy - py * ux);
                    if (px * ux + py * uy < 0) distance += 1;   // behind the exit point
                }
                if (distance < bestDistance) { bestDistance = distance; best = i; }
            });
            return best;
        }

        /** The cursor line within a few pixels of a press: {key: 'u_ref' ...} or null. */
        grabLine(e) {
            const box = this.overlay.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            const px = (e.clientX - box.left) * ratio, py = (e.clientY - box.top) * ratio;
            const reach = 6 * ratio;
            for (const key of ['u_meas', 'i_meas', 'u_ref', 'i_ref']) {
                const value = this.cursors[key];
                if (value === null || value === undefined) continue;
                const [sx, sy] = key.startsWith('u') ? this.toScreen(0, value) : this.toScreen(value, 0);
                if (key.startsWith('u') ? Math.abs(py - sy) <= reach : Math.abs(px - sx) <= reach) return key;
            }
            return null;
        }

        bind() {
            const el = this.overlay;
            let drag = null;
            el.addEventListener('contextmenu', e => e.preventDefault());
            el.addEventListener('pointerdown', e => {
                if (!this.rays) return;
                el.setPointerCapture(e.pointerId);
                if (e.button === 2 || e.button === 1) {
                    drag = { pan: true, x: e.clientX, y: e.clientY, view: this.currentView() };
                } else if (e.button === 0) {
                    const [x, y] = this.toWorld(e);
                    const line = this.grabLine(e);
                    if (e.altKey && this.weld && this.showWeld) {   // Alt+drag: move the weld's centre line
                        drag = { weld: true, x, shift: this.weldShift || 0 };
                    } else if (line) {
                        drag = { line };
                    } else if (e.shiftKey || e.ctrlKey) {
                        const which = e.shiftKey ? 'meas' : 'ref';
                        this.options.onCursors?.({ [`u_${which}`]: y, [`i_${which}`]: x });
                        drag = { pair: which };
                    } else {
                        drag = { pan: false };
                        this.options.onCursor(this.pick([x, y]));
                    }
                }
            });
            el.addEventListener('pointermove', e => {
                if (!this.rays) return;
                const [x, y] = this.toWorld(e);
                this.options.onHover?.(x, y);
                if (!drag) {
                    const line = this.grabLine(e);
                    el.style.cursor = e.altKey && this.weld && this.showWeld ? 'ew-resize'
                        : line ? (line.startsWith('u') ? 'ns-resize' : 'ew-resize') : '';
                    return;
                }
                if (drag.weld) {
                    this.setWeldShift(drag.shift + x - drag.x);
                    this.options.onWeldShift?.(this.weldShift, false);
                    return;
                }
                if (drag.line) {
                    this.options.onCursors?.({ [drag.line]: drag.line.startsWith('u') ? y : x });
                    return;
                }
                if (drag.pair) {
                    this.options.onCursors?.({ [`u_${drag.pair}`]: y, [`i_${drag.pair}`]: x });
                    return;
                }
                if (drag.pan) {
                    const box = el.getBoundingClientRect();
                    const [cx, cy, width, height] = drag.view;
                    this.view = [cx - (e.clientX - drag.x) / box.width * width, cy - (e.clientY - drag.y) / box.height * height, width, height];
                    this.draw();
                } else {
                    this.options.onCursor(this.pick([x, y]));
                }
            });
            const end = () => {
                if (drag?.weld) this.options.onWeldShift?.(this.weldShift, true);
                drag = null;
            };
            el.addEventListener('pointerup', end);
            el.addEventListener('pointercancel', end);
            el.addEventListener('pointerleave', () => this.options.onHover?.(null));
            el.addEventListener('dblclick', () => { this.view = null; this.draw(); });
            el.addEventListener('wheel', e => {
                if (!this.rays) return;
                e.preventDefault();
                const [px, py] = this.toWorld(e);
                const [cx, cy, width, height] = this.currentView();
                const f = Math.exp(e.deltaY * 0.0015);
                const fit = this.fitView()[2];
                const next = Math.min(Math.max(width * f, fit / 40), fit * 2);
                const k = next / width;
                this.view = [px - (px - cx) * k, py - (py - cy) * k, next, height * k];
                this.draw();
            }, { passive: false });
        }
    }

    return SScanView;
})();
