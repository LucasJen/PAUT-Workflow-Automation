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

    return {
        get,
        /** [[name, label]] of a kind's palettes ('amplitude' or 'range'). */
        list: kind => Object.entries(PALETTES[kind]).map(([name, [label]]) => [name, label]),
        amplitude: () => get('amplitude', 'omnipc'),
        thickness: () => get('range', 'omnipc'),
    };
})();
