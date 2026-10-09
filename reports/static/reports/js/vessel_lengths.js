// Lengths as typed on vessel drawings, stored in inches: feet-inches as the client drawings write
// them (14'-0", 5'-6 1/2", 66", 66) or millimetres when metric (1676, 1676 mm). The same reading as
// reports/services/vessel/lengths.py. Used by vessel.js and vessel_coverage.js.

window.VesselLengths = (function () {
    const MM_PER_IN = 25.4;

    function inchesPart(text) {
        let total = 0;
        for (const token of text.trim().split(/[\s-]+/)) {
            if (!token) continue;
            const fraction = token.match(/^(\d+)\/(\d+)$/);
            if (fraction) {
                if (+fraction[2] === 0) throw new Error(token);
                total += +fraction[1] / +fraction[2];
            } else if (/^\d*\.?\d+$/.test(token)) {
                total += parseFloat(token);
            } else {
                throw new Error(token);
            }
        }
        return total;
    }

    /** Inches for a typed length, null when blank; throws when it can't be read. */
    function parseLength(text, isMetric = false) {
        let t = String(text ?? '').trim().toLowerCase().replace(/′/g, "'").replace(/″|''/g, '"');
        if (!t) return null;
        if (t.endsWith('mm')) {
            const mm = parseFloat(t.slice(0, -2));
            if (Number.isNaN(mm)) throw new Error(text);
            return mm / MM_PER_IN;
        }
        if (isMetric && !t.includes("'") && !t.includes('"')) {
            if (!/^\d*\.?\d+$/.test(t)) throw new Error(text);
            return parseFloat(t) / MM_PER_IN;
        }
        t = t.replace(/ft/g, "'").replace(/in/g, '"');
        const at = t.lastIndexOf("'");
        const feet = at >= 0 ? t.slice(0, at).trim() : '';
        if (feet && !/^\d*\.?\d+$/.test(feet)) throw new Error(text);
        const rest = (at >= 0 ? t.slice(at + 1) : t).replace(/"/g, ' ').replace(/^[\s-]+/, '');
        return (feet ? parseFloat(feet) * 12 : 0) + inchesPart(rest);
    }

    function inchesText(inches) {
        let whole = Math.floor(inches);
        let sixteenths = Math.round((inches - whole) * 16);
        if (sixteenths >= 16) { whole += 1; sixteenths -= 16; }
        if (!sixteenths) return String(whole);
        let n = sixteenths, d = 16;
        while (n % 2 === 0) { n /= 2; d /= 2; }
        return whole ? `${whole} ${n}/${d}` : `${n}/${d}`;
    }

    /** A stored length as it shows: '1676 mm', or ft-in from `feetFrom` inches up and inches below. */
    function formatLength(inches, isMetric = false, feetFrom = 36) {
        if (inches === null || inches === undefined || inches === '') return '';
        if (isMetric) return `${+(inches * MM_PER_IN).toFixed(1)} mm`;
        const value = Math.round(inches * 16) / 16;
        if (Math.abs(value) >= feetFrom) {
            const sign = value < 0 ? '-' : '';
            const abs = Math.abs(value);
            const feet = Math.floor(abs / 12);
            return `${sign}${feet}'-${inchesText(abs - feet * 12)}"`;
        }
        return value < 0 ? `-${inchesText(-value)}"` : `${inchesText(value)}"`;
    }
    const formatDiameter = (inches, isMetric = false) => formatLength(inches, isMetric, 120);

    return { parseLength, formatLength, formatDiameter };
})();
