// A 2D image view drawn with WebGL2 - the C-scan (scan x line) and the B-scan (scan x depth). The
// data is a texture of values; the shader maps them through the amplitude palette (with soft gain)
// or a thickness / depth palette over a min-max range, NaN shown as no data. A 2D overlay canvas
// draws the axes and the linked cursors. Stretched to fill the panel; scroll to zoom at the pointer,
// right-drag to pan, double-click to fit. Click or drag reports the cell under the pointer.
//
// Columns run along x and rows along y: x = x0 + column * dx, y = y0 + row * dy (y down). The data
// array is row-major [outer][inner]; `transpose` says the outer index is the column (a C-scan's
// [scan][line] with scan across). No data (NaN) goes up as a large negative number.

window.ImageView = (function () {
    const VERTEX = `#version 300 es
in vec2 aPos;
in vec2 aTex;
uniform vec4 uView;
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
uniform int uMode;          // 0 amplitude (%), 1 range
uniform float uGain;
uniform vec2 uRange;
out vec4 outColor;
void main() {
    float a = texture(uData, vTex).r;
    if (a < -1000.0 || (uMode == 0 && a < -0.5)) {   // no data: white on a range palette (like OmniPC), grey on amplitude
        outColor = uMode == 0 ? vec4(0.62, 0.64, 0.68, 1.0) : vec4(1.0);
        return;
    }
    float p = uMode == 0 ? a * uGain / 100.0 : (a - uRange.x) / max(uRange.y - uRange.x, 1e-12);
    p = clamp(p, 0.0, 1.0);
    outColor = texture(uPalette, vec2(p * (255.0 / 256.0) + 0.5 / 256.0, 0.5));
}`;

    function compile(gl, type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
        return shader;
    }

    class ImageView {
        /** options: {formatX(v), formatY(v), onPick({column, row, x, y, event}), unitLength()} */
        constructor(stage, options) {
            this.options = options;
            this.canvas = Object.assign(document.createElement('canvas'), { className: 'analysis-gl' });
            this.overlay = Object.assign(document.createElement('canvas'), { className: 'analysis-overlay' });
            stage.append(this.canvas, this.overlay);
            const gl = this.canvas.getContext('webgl2', { antialias: false, preserveDrawingBuffer: true });
            if (!gl) throw new Error('This browser has no WebGL2.');
            this.gl = gl;
            const program = gl.createProgram();
            gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
            gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
            gl.linkProgram(program);
            this.program = program;
            const u = name => gl.getUniformLocation(program, name);
            this.loc = { pos: gl.getAttribLocation(program, 'aPos'), tex: gl.getAttribLocation(program, 'aTex'),
                         view: u('uView'), data: u('uData'), palette: u('uPalette'), mode: u('uMode'),
                         gain: u('uGain'), range: u('uRange') };
            this.buffer = gl.createBuffer();
            this.dataTexture = gl.createTexture();
            this.paletteTextures = {};
            this.gain = 1;
            this.mode = 'amplitude';
            this.range = [0, 1];
            this.view = null;
            this.cursors = { x: [], y: [] };    // [{value, colour}]
            this.bind();
            new ResizeObserver(() => this.draw()).observe(stage);
        }

        paletteTexture(name) {
            const gl = this.gl;
            if (!this.paletteTextures[name]) {
                const t = gl.createTexture();
                gl.bindTexture(gl.TEXTURE_2D, t);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
                              name === 'range' ? AnalysisPalette.thickness() : AnalysisPalette.amplitude());
                this.filter(gl.LINEAR);
                this.paletteTextures[name] = t;
            }
            return this.paletteTextures[name];
        }

        filter(mode) {
            const gl = this.gl;
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        }

        /**
         * values: Float32Array [outer][inner]; outer x inner = the array's shape.
         * axes: {x0, dx, y0, dy} (column / row centres in world units); transpose: outer = columns;
         * mode: 'amplitude' | 'range'; range: [min, max] for 'range'.
         */
        setImage(values, outer, inner, { axes, transpose = false, mode = 'amplitude', range = null, keepView = false, smooth = false }) {
            const gl = this.gl;
            gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
            gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            // NaN (no data) becomes a sentinel: shaders can't be trusted to test for NaN (some drivers
            // optimise it away and it reads as the bottom of the palette)
            const upload = new Float32Array(values.length);
            for (let i = 0; i < values.length; i++) upload[i] = Number.isNaN(values[i]) ? -60000 : values[i];
            // Smooth: blended between rows and columns (half floats can be filtered everywhere) - between
            // a sectorial scan's beams, like OmniPC; otherwise cells, each a real position
            gl.texImage2D(gl.TEXTURE_2D, 0, smooth ? gl.R16F : gl.R32F, inner, outer, 0, gl.RED, gl.FLOAT, upload);
            this.filter(smooth ? gl.LINEAR : gl.NEAREST);
            this.columns = transpose ? outer : inner;
            this.rows = transpose ? inner : outer;
            this.axes = axes;
            this.mode = mode;
            if (range) this.range = range;
            const { x0, dx, y0, dy } = axes;
            const xa = x0 - dx / 2, xb = x0 + (this.columns - 0.5) * dx;
            const ya = y0 - dy / 2, yb = y0 + (this.rows - 0.5) * dy;
            // Texture s runs along the inner index and t along the outer one
            const verts = transpose
                ? [xa, ya, 0, 0, xb, ya, 0, 1, xb, yb, 1, 1, xa, ya, 0, 0, xb, yb, 1, 1, xa, yb, 1, 0]
                : [xa, ya, 0, 0, xb, ya, 1, 0, xb, yb, 1, 1, xa, ya, 0, 0, xb, yb, 1, 1, xa, yb, 0, 1];
            gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);
            this.bounds = [Math.min(xa, xb), Math.min(ya, yb), Math.max(xa, xb), Math.max(ya, yb)];
            if (!keepView) this.view = null;
            this.hasImage = true;
            this.draw();
        }

        setGain(db) { this.gain = Math.pow(10, db / 20); this.draw(); }
        setRange(range) { this.range = range; this.draw(); }
        setCursors(cursors) { this.cursors = cursors; this.drawOverlay(); }

        clear(message) {
            this.hasImage = false;
            this.message = message;
            this.draw();
        }

        // ── view ──
        fitView() {
            const [x0, y0, x1, y1] = this.bounds;
            return [(x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 1.02, (y1 - y0) * 1.04];
        }
        currentView() { return this.view || this.fitView(); }

        toWorld(e) {
            const box = this.canvas.getBoundingClientRect();
            const [cx, cy, w, h] = this.currentView();
            return [cx + ((e.clientX - box.left) / box.width - 0.5) * w, cy + ((e.clientY - box.top) / box.height - 0.5) * h];
        }
        toScreen(x, y) {
            const [cx, cy, w, h] = this.currentView();
            return [((x - cx) / w + 0.5) * this.overlay.width, ((y - cy) / h + 0.5) * this.overlay.height];
        }
        cell([x, y]) {
            const { x0, dx, y0, dy } = this.axes;
            return [Math.round((x - x0) / dx), Math.round((y - y0) / dy)];
        }

        resize() {
            const ratio = window.devicePixelRatio || 1;
            for (const c of [this.canvas, this.overlay]) {
                const w = Math.max(1, Math.round(c.clientWidth * ratio)), h = Math.max(1, Math.round(c.clientHeight * ratio));
                if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
            }
        }

        draw() {
            this.resize();
            const gl = this.gl;
            gl.viewport(0, 0, this.canvas.width, this.canvas.height);
            gl.clearColor(0.06, 0.07, 0.09, 1);
            gl.clear(gl.COLOR_BUFFER_BIT);
            if (this.hasImage) {
                gl.useProgram(this.program);
                const [cx, cy, w, h] = this.currentView();
                gl.uniform4f(this.loc.view, cx, cy, 2 / w, 2 / h);
                gl.uniform1i(this.loc.mode, this.mode === 'amplitude' ? 0 : 1);
                gl.uniform1f(this.loc.gain, this.gain);
                gl.uniform2f(this.loc.range, this.range[0], this.range[1]);
                gl.activeTexture(gl.TEXTURE0);
                gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
                gl.uniform1i(this.loc.data, 0);
                gl.activeTexture(gl.TEXTURE1);
                gl.bindTexture(gl.TEXTURE_2D, this.paletteTexture(this.mode === 'amplitude' ? 'amplitude' : 'range'));
                gl.uniform1i(this.loc.palette, 1);
                gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
                gl.enableVertexAttribArray(this.loc.pos);
                gl.vertexAttribPointer(this.loc.pos, 2, gl.FLOAT, false, 16, 0);
                gl.enableVertexAttribArray(this.loc.tex);
                gl.vertexAttribPointer(this.loc.tex, 2, gl.FLOAT, false, 16, 8);
                gl.drawArrays(gl.TRIANGLES, 0, 6);
            }
            this.drawOverlay();
        }

        drawOverlay() {
            const ctx = this.overlay.getContext('2d');
            const ratio = window.devicePixelRatio || 1;
            const w = this.overlay.width, h = this.overlay.height;
            ctx.clearRect(0, 0, w, h);
            ctx.font = `${11 * ratio}px Inter, Arial, sans-serif`;
            if (!this.hasImage) {
                if (this.message) {
                    ctx.fillStyle = '#cbd5e1';
                    ctx.fillText(this.message, 12 * ratio, 22 * ratio);
                }
                return;
            }
            for (const c of this.cursors.x) {
                if (c.value === null || c.value === undefined) continue;
                const [x] = this.toScreen(c.value, 0);
                ctx.strokeStyle = c.colour; ctx.lineWidth = (c.width || 1) * ratio;
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            }
            for (const c of this.cursors.y) {
                if (c.value === null || c.value === undefined) continue;
                const [, y] = this.toScreen(0, c.value);
                ctx.strokeStyle = c.colour; ctx.lineWidth = (c.width || 1) * ratio;
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
            }
            const [cx, cy, vw, vh] = this.currentView();
            const step = (span, pixels, unit) => {
                const target = span / unit / Math.max(2, pixels / (75 * ratio));
                const mag = Math.pow(10, Math.floor(Math.log10(target)));
                return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= target) * unit;
            };
            const label = (text, x, y) => {
                ctx.save(); ctx.strokeStyle = 'rgba(8,10,14,0.9)'; ctx.lineWidth = 3 * ratio; ctx.lineJoin = 'round';
                ctx.strokeText(text, x, y); ctx.restore(); ctx.fillStyle = '#e2e8f0'; ctx.fillText(text, x, y);
            };
            ctx.strokeStyle = '#94a3b8';
            ctx.lineWidth = ratio;
            const xUnit = this.options.xUnit ? this.options.xUnit() : 1, yUnit = this.options.yUnit ? this.options.yUnit() : 1;
            const xs = step(vw, w, xUnit), ys = step(vh, h, yUnit);
            for (let x = Math.ceil((cx - vw / 2) / xs) * xs; x <= cx + vw / 2; x += xs) {
                const [sx] = this.toScreen(x, 0);
                ctx.beginPath(); ctx.moveTo(sx, h); ctx.lineTo(sx, h - 5 * ratio); ctx.stroke();
                label(this.options.formatX(x), sx + 2 * ratio, h - 5 * ratio);
            }
            for (let y = Math.ceil((cy - vh / 2) / ys) * ys; y <= cy + vh / 2; y += ys) {
                const [, sy] = this.toScreen(0, y);
                ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(5 * ratio, sy); ctx.stroke();
                label(this.options.formatY(y), 7 * ratio, sy + 4 * ratio);
            }
        }

        // ── pointer ──
        bind() {
            const el = this.overlay;
            let drag = null;
            el.addEventListener('contextmenu', e => e.preventDefault());
            const pick = e => {
                const [x, y] = this.toWorld(e);
                const [column, row] = this.cell([x, y]);
                this.options.onPick?.({ column, row, x, y, event: e, inside: column >= 0 && column < this.columns && row >= 0 && row < this.rows });
            };
            el.addEventListener('pointerdown', e => {
                if (!this.hasImage) return;
                el.setPointerCapture(e.pointerId);
                if (e.button === 1 || e.button === 2) drag = { pan: true, x: e.clientX, y: e.clientY, view: this.currentView() };
                else if (e.button === 0) { drag = { pan: false }; pick(e); }
            });
            el.addEventListener('pointermove', e => {
                if (!this.hasImage) return;
                const [x, y] = this.toWorld(e);
                this.options.onHover?.(x, y, this.cell([x, y]));
                if (!drag) return;
                if (drag.pan) {
                    const box = el.getBoundingClientRect();
                    const [cx, cy, w, h] = drag.view;
                    this.view = [cx - (e.clientX - drag.x) / box.width * w, cy - (e.clientY - drag.y) / box.height * h, w, h];
                    this.draw();
                } else {
                    pick(e);
                }
            });
            const end = () => { drag = null; };
            el.addEventListener('pointerup', end);
            el.addEventListener('pointercancel', end);
            el.addEventListener('pointerleave', () => this.options.onHover?.(null));
            el.addEventListener('dblclick', () => { this.view = null; this.draw(); });
            el.addEventListener('wheel', e => {
                if (!this.hasImage) return;
                e.preventDefault();
                const [px, py] = this.toWorld(e);
                const [cx, cy, w, h] = this.currentView();
                const fit = this.fitView();
                const k = Math.min(Math.max(Math.exp(e.deltaY * 0.0015), fit[2] / 200 / w), fit[2] * 2 / w);
                this.view = [px - (px - cx) * k, py - (py - cy) * k, w * k, h * k];
                this.draw();
            }, { passive: false });
        }
    }

    return ImageView;
})();
