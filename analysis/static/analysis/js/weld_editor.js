// The Geometry panel's weld overlay editor: the weld's centre line across the index (also Alt+drag
// on the S-scan) and its shape - root gap, land, root / hot pass / fills (height at an angle from
// vertical, from the root up) and the caps - in the .nde's weldGeometry terms, starting from the
// file's own. Lengths are typed in the page's units and kept in metres. The page draws the outline
// (the server's weld_outline) and remembers the edits; this only owns the form.

window.WeldEditor = (function () {
    const el = (tag, props = {}, ...children) => {
        const node = Object.assign(document.createElement(tag), props);
        node.append(...children);
        return node;
    };

    return class WeldEditor {
        /**
         * box: element to fill. options: {unitLength() (m per unit), units() ('in' | 'mm'), format(m),
         * onShape(shape), onShift(m), onReset(), onCreate()}
         */
        constructor(box, options) {
            this.box = box;
            this.options = options;
            this.shape = null;
        }

        /** Rebuilds the form: {shape, shift, edited, thickness} or {message, canCreate}. */
        show({ shape = null, shift = 0, edited = false, thickness = 0, message = '', canCreate = false }) {
            this.shape = shape ? structuredClone(shape) : null;
            this.thickness = thickness;
            if (!this.shape) {
                const parts = [el('p', { className: 'analysis-note', textContent: message })];
                if (canCreate) {
                    const draw = el('button', { type: 'button', className: 'btn btn-sm btn-secondary', innerHTML: '<i class="bi bi-plus-lg"></i> Draw a weld' });
                    draw.title = 'Start from a usual single-V bevel and adjust it to the weld';
                    draw.addEventListener('click', () => this.options.onCreate());
                    parts.push(el('div', {}, draw));
                }
                this.box.replaceChildren(...parts);
                return;
            }
            const u = this.options.units();
            const grid = el('div', { className: 'analysis-weld-grid' });
            const row = (label, help, ...controls) => {
                const name = el('label', { textContent: label, title: help });
                grid.append(name, el('div', { className: 'analysis-weld-controls' }, ...controls));
            };

            // Centre line: where the weld is across the index
            this.shiftInput = this.number(shift / this.options.unitLength(), v => this.options.onShift(v * this.options.unitLength()), true);
            const step = u === 'mm' ? 0.5 : 0.02;
            const nudge = (sign, icon) => {
                const b = el('button', { type: 'button', className: 'btn btn-sm btn-ghost', innerHTML: `<i class="bi bi-${icon}"></i>` });
                b.title = `Move it ${sign < 0 ? 'left' : 'right'} by ${step} ${u}`;
                b.addEventListener('click', () => {
                    const v = (parseFloat(this.shiftInput.value) || 0) + sign * step;
                    this.shiftInput.value = this.fmt(v);
                    this.options.onShift(v * this.options.unitLength());
                });
                return b;
            };
            row('Centre line', 'Where the weld centre is across the index, from the file\'s index origin. Alt+drag the weld on the S-scan to move it.',
                nudge(-1, 'chevron-left'), this.shiftInput, nudge(1, 'chevron-right'), el('span', { className: 'analysis-tool-note', textContent: u }));

            const s = this.shape;
            row('Root gap', 'The gap between the plates at the root (both sides)',
                this.number(2 * (s.offset || 0) / this.options.unitLength(), v => { s.offset = Math.max(0, v) * this.options.unitLength() / 2; }),
                el('span', { className: 'analysis-tool-note', textContent: u }));
            s.land = s.land || {};
            row('Land', 'Height of the root face (straight up from the root)',
                this.number((s.land.height || 0) / this.options.unitLength(), v => { s.land.height = Math.max(0, v) * this.options.unitLength(); }),
                el('span', { className: 'analysis-tool-note', textContent: u }));
            s.root = s.root || {};
            s.hotPass = s.hotPass || {};
            s.fills = s.fills || [];
            row('Root', 'The root pass: its height and its face angle from vertical', ...this.pass(s.root));
            row('Hot pass', 'The hot pass: its height and its face angle from vertical', ...this.pass(s.hotPass));
            s.fills.forEach((fill, i) => {
                const remove = el('button', { type: 'button', className: 'btn btn-sm btn-ghost', innerHTML: '<i class="bi bi-x-lg"></i>', title: 'Remove this fill' });
                remove.addEventListener('click', () => { s.fills.splice(i, 1); this.changed(true); });
                row(s.fills.length > 1 ? `Fill ${i + 1}` : 'Fill', 'A fill pass: its height and its face angle from vertical', ...this.pass(fill), remove);
            });
            const add = el('button', { type: 'button', className: 'btn btn-sm btn-link analysis-weld-add', innerHTML: '<i class="bi bi-plus-lg"></i> Fill' });
            add.title = 'Add a fill pass above the others (a compound bevel)';
            add.addEventListener('click', () => { s.fills.push({ angle: s.fills.at(-1)?.angle ?? 37.5, height: 0 }); this.changed(true); });
            grid.append(el('span'), el('div', {}, add));
            s.upperCap = s.upperCap || {};
            s.lowerCap = s.lowerCap || {};
            row('Cap', 'Weld cap: width across, height above the surface', ...this.cap(s.upperCap));
            row('Root cap', 'Root reinforcement: width across, height below the back wall', ...this.cap(s.lowerCap));

            this.note = el('p', { className: 'analysis-note' });
            const status = el('div', { className: 'analysis-drawer-row' },
                el('span', { className: 'analysis-note', textContent: edited ? 'Edited here (kept for this file).' : "From the file's setup (MXU / OmniPC)." }));
            if (edited) {
                const reset = el('button', { type: 'button', className: 'btn btn-sm btn-secondary ms-auto', innerHTML: '<i class="bi bi-arrow-counterclockwise"></i> File\'s weld' });
                reset.title = "Back to the weld from the file's setup, centred";
                reset.addEventListener('click', () => this.options.onReset());
                status.append(reset);
            }
            this.box.replaceChildren(grid, this.note, status);
            this.checkHeight();
        }

        /** The centre line from a drag on the S-scan. */
        setShift(shift) {
            if (this.shiftInput) this.shiftInput.value = this.fmt(shift / this.options.unitLength());
        }

        fmt(v) {
            return this.options.units() === 'mm' ? v.toFixed(2) : v.toFixed(3);
        }

        number(value, apply, isShift = false) {
            const input = el('input', { type: 'text', inputMode: 'decimal', className: 'form-control form-control-sm mono', value: this.fmt(value || 0) });
            input.addEventListener('change', () => {
                const v = parseFloat(input.value);
                if (!Number.isFinite(v)) { input.value = this.fmt(0); return; }
                apply(v);
                if (!isShift) this.changed();
            });
            return input;
        }

        angle(p) {
            const input = el('input', { type: 'text', inputMode: 'decimal', className: 'form-control form-control-sm mono analysis-weld-angle', value: String(p.angle || 0) });
            input.title = 'Face angle from vertical (degrees)';
            input.addEventListener('change', () => {
                const v = parseFloat(input.value);
                p.angle = Number.isFinite(v) ? Math.min(80, Math.max(0, v)) : 0;
                input.value = String(p.angle);
                this.changed();
            });
            return input;
        }

        pass(p) {
            return [this.number((p.height || 0) / this.options.unitLength(), v => { p.height = Math.max(0, v) * this.options.unitLength(); }),
                    el('span', { className: 'analysis-tool-note', textContent: '@' }), this.angle(p), el('span', { className: 'analysis-tool-note', textContent: '°' })];
        }

        cap(c) {
            const width = this.number((c.width || 0) / this.options.unitLength(), v => { c.width = Math.max(0, v) * this.options.unitLength(); });
            const height = this.number((c.height || 0) / this.options.unitLength(), v => { c.height = Math.max(0, v) * this.options.unitLength(); });
            width.title = 'Width'; height.title = 'Height';
            return [width, el('span', { className: 'analysis-tool-note', textContent: '×' }), height];
        }

        /** Tells the page; `rebuild` when rows were added / removed. */
        changed(rebuild = false) {
            this.options.onShape(structuredClone(this.shape), rebuild);
            this.checkHeight();
        }

        /** Whether the bevel's heights add up to the part's thickness, like the file's do. */
        checkHeight() {
            if (!this.note || !this.thickness) return;
            const s = this.shape;
            const total = (s.land?.height || 0) + (s.root?.height || 0) + (s.hotPass?.height || 0) + (s.fills || []).reduce((t, f) => t + (f.height || 0), 0);
            const off = total - this.thickness;
            this.note.textContent = Math.abs(off) <= this.thickness * 0.01 ? ''
                : off < 0 ? `The heights add up to ${this.options.format(total)} of the ${this.options.format(this.thickness)} wall: the last face runs on straight to the surface.`
                    : `The heights add up to ${this.options.format(total)}, more than the ${this.options.format(this.thickness)} wall: the bevel stops at the surface.`;
        }
    };
})();
