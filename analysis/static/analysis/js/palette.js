// Colour palettes for the Analysis views: 256 RGBA entries. Amplitude: 0-100 % of full screen height,
// like OmniPC's default (white at nothing, through blues, green and yellow to red). Thickness: a
// min-max range, red (thin) to blue (thick).

window.AnalysisPalette = (function () {
    const AMPLITUDE = [
        [0.00, [255, 255, 255]],
        [0.12, [214, 230, 247]],
        [0.25, [120, 170, 235]],
        [0.38, [40, 80, 210]],
        [0.48, [20, 30, 140]],
        [0.58, [0, 150, 90]],
        [0.70, [150, 210, 30]],
        [0.80, [245, 230, 0]],
        [0.90, [245, 130, 0]],
        [1.00, [205, 0, 0]],
    ];

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

    // Thickness / depth over a range, like OmniPC's thickness palette: thin (low) red through yellow,
    // green and cyan to blue (thick)
    const THICKNESS = [
        [0.00, [200, 0, 0]],
        [0.20, [245, 120, 0]],
        [0.40, [240, 220, 0]],
        [0.60, [40, 180, 60]],
        [0.80, [0, 170, 220]],
        [1.00, [30, 60, 200]],
    ];

    const amplitude = build(AMPLITUDE);
    const thickness = build(THICKNESS);
    return {
        amplitude: () => amplitude,
        thickness: () => thickness,
        /** CSS colour of a percentage (0-100), for legends. */
        css(percent) {
            const i = Math.max(0, Math.min(255, Math.round(percent * 2.55))) * 4;
            return `rgb(${amplitude[i]}, ${amplitude[i + 1]}, ${amplitude[i + 2]})`;
        },
    };
})();
