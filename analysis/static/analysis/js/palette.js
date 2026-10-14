// Colour palettes for the Analysis views: 256 RGBA entries each. Amplitude palettes run over 0-100 %
// of full screen height; thickness / depth palettes over a min-max range. The page lets the user pick
// one of each (remembered in this browser).

window.AnalysisPalette = (function () {
    const PALETTES = {
        amplitude: {
            omnipc: ['OmniPC', [   // white at nothing, through blues, green and yellow to red
                [0.00, [255, 255, 255]], [0.12, [214, 230, 247]], [0.25, [120, 170, 235]], [0.38, [40, 80, 210]],
                [0.48, [20, 30, 140]], [0.58, [0, 150, 90]], [0.70, [150, 210, 30]], [0.80, [245, 230, 0]],
                [0.90, [245, 130, 0]], [1.00, [205, 0, 0]]]],
            rainbow: ['Rainbow', [
                [0.00, [0, 0, 120]], [0.20, [0, 70, 255]], [0.40, [0, 220, 255]], [0.60, [120, 255, 120]],
                [0.80, [255, 200, 0]], [1.00, [200, 0, 0]]]],
            hot: ['Hot', [
                [0.00, [0, 0, 0]], [0.35, [180, 0, 0]], [0.65, [255, 140, 0]], [0.85, [255, 230, 60]], [1.00, [255, 255, 255]]]],
            grey: ['Grey', [[0.00, [0, 0, 0]], [1.00, [255, 255, 255]]]],
            grey_inverted: ['Grey (white at 0)', [[0.00, [255, 255, 255]], [1.00, [0, 0, 0]]]],
        },
        range: {
            omnipc: ['OmniPC thickness', [   // thin (low) red through yellow, green and cyan to blue (thick)
                [0.00, [200, 0, 0]], [0.20, [245, 120, 0]], [0.40, [240, 220, 0]], [0.60, [40, 180, 60]],
                [0.80, [0, 170, 220]], [1.00, [30, 60, 200]]]],
            reversed: ['Reversed (thin blue)', [
                [0.00, [30, 60, 200]], [0.20, [0, 170, 220]], [0.40, [40, 180, 60]], [0.60, [240, 220, 0]],
                [0.80, [245, 120, 0]], [1.00, [200, 0, 0]]]],
            lsi: ['LSI', [   // thin (low) red through orange and yellow to green (thick)
                [0.00, [200, 0, 0]], [0.25, [240, 90, 0]], [0.45, [250, 170, 0]], [0.62, [245, 230, 0]],
                [0.80, [130, 200, 40]], [1.00, [0, 150, 50]]]],
            rainbow: ['Rainbow', [
                [0.00, [120, 0, 160]], [0.20, [0, 60, 255]], [0.40, [0, 210, 230]], [0.60, [60, 220, 60]],
                [0.80, [255, 220, 0]], [1.00, [220, 0, 0]]]],
            grey: ['Grey', [[0.00, [0, 0, 0]], [1.00, [255, 255, 255]]]],
        },
    };

    function build(stops) {
        const out = new Uint8Array(256 * 4);
        for (let i = 0; i < 256; i++) {
            const x = i / 255;
            let k = 0;
            while (k < stops.length - 2 && x > stops[k + 1][0]) k++;
            const [x0, c0] = stops[k], [x1, c1] = stops[k + 1];
            const f = Math.min(1, Math.max(0, (x - x0) / (x1 - x0)));
            for (let c = 0; c < 3; c++) out[i * 4 + c] = Math.round(c0[c] + (c1[c] - c0[c]) * f);
            out[i * 4 + 3] = 255;
        }
        return out;
    }

    const built = {};
    function get(kind, name) {
        const set = PALETTES[kind];
        const key = set[name] ? name : 'omnipc';
        return (built[`${kind}:${key}`] ||= build(set[key][1]));
    }

    /** Draws a palette as a vertical colour bar (top = the high end) with labels, on a 2D canvas. */
    function legend(ctx, kind, name, x, y, width, height, top, bottom, ratio = 1) {
        const colours = get(kind, name);
        for (let i = 0; i < height; i++) {
            const k = Math.round((1 - i / Math.max(1, height - 1)) * 255) * 4;
            ctx.fillStyle = `rgb(${colours[k]}, ${colours[k + 1]}, ${colours[k + 2]})`;
            ctx.fillRect(x, y + i, width, 1);
        }
        ctx.strokeStyle = 'rgba(255,255,255,0.5)';
        ctx.lineWidth = ratio;
        ctx.strokeRect(x, y, width, height);
        ctx.save();
        ctx.font = `${10 * ratio}px Inter, Arial, sans-serif`;
        ctx.textAlign = 'right';
        ctx.lineWidth = 3 * ratio;
        ctx.strokeStyle = 'rgba(8,10,14,0.9)';
        for (const [text, ty] of [[top, y + 9 * ratio], [bottom, y + height]]) {
            ctx.strokeText(text, x - 3 * ratio, ty);
            ctx.fillStyle = '#e2e8f0';
            ctx.fillText(text, x - 3 * ratio, ty);
        }
        ctx.restore();
    }

    /**
     * A dashed line that stays visible on any image: each dash black where the picture under it is
     * light (the white of a quiet S-scan), white where it's dark. `pixels` is a view's PixelReader.
     */
    function contrastDash(ctx, pixels, x0, y0, x1, y1, ratio) {
        const len = Math.hypot(x1 - x0, y1 - y0);
        if (!len) return;
        const on = 6 * ratio, off = 5 * ratio;
        ctx.save();
        ctx.setLineDash([]);
        ctx.lineWidth = Math.max(1, 1.2 * ratio);
        for (let d = 0; d < len; d += on + off) {
            const a = d / len, b = Math.min(d + on, len) / len;
            const mid = (a + b) / 2;
            const light = pixels ? pixels.light(x0 + (x1 - x0) * mid, y0 + (y1 - y0) * mid) : false;
            ctx.strokeStyle = light ? 'rgba(0, 0, 0, 0.85)' : 'rgba(255, 255, 255, 0.8)';
            ctx.beginPath();
            ctx.moveTo(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a);
            ctx.lineTo(x0 + (x1 - x0) * b, y0 + (y1 - y0) * b);
            ctx.stroke();
        }
        ctx.restore();
    }

    /**
     * Reads a WebGL canvas's pixels once per drawing (the canvas keeps its drawing buffer) and says
     * whether a point (overlay pixels, same size as the canvas) is light. invalidate() after each draw.
     */
    class PixelReader {
        constructor(gl) { this.gl = gl; this.data = null; }
        invalidate() { this.data = null; }
        light(x, y) {
            const gl = this.gl, w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
            if (!this.data || this.data.length !== w * h * 4) {
                this.data = new Uint8Array(w * h * 4);
                gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, this.data);
            }
            const px = Math.min(w - 1, Math.max(0, Math.round(x))), py = Math.min(h - 1, Math.max(0, h - 1 - Math.round(y)));
            const i = (py * w + px) * 4;
            return 0.299 * this.data[i] + 0.587 * this.data[i + 1] + 0.114 * this.data[i + 2] > 150;
        }
    }

    return {
        get,
        legend,
        contrastDash,
        PixelReader,
        /** [[name, label]] of a kind's palettes ('amplitude' or 'range'). */
        list: kind => Object.entries(PALETTES[kind]).map(([name, [label]]) => [name, label]),
        amplitude: () => get('amplitude', 'omnipc'),
        thickness: () => get('range', 'omnipc'),
    };
})();
