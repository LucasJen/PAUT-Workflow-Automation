// Grading indications against the acceptance criteria of 100-UT-020 (Rev 9) - pure functions, used by
// the Analysis page's Indications panel and run on their own by the Validation page's case table (L5).
// B31.1 (§8): cracks, lack of fusion and incomplete penetration fail at any length; other discontinuities
// fail over the reference level and longer than allowed. B31.3 (§9): over the reference level and longer
// than allowed. Allowed: 0.25 in for T up to 0.75 in, T/3 up to 2.25 in, 0.75 in over (T: the thinner member).
// The page can't tell what a discontinuity is, so under B31.1 one over 20 % of reference (§8's
// investigation level) that doesn't fail on amplitude and length is yellow: characterise it.
// Lengths in m; amplitudes in % of full screen.

window.AnalysisCriteria = (function () {
    const IN = 0.0254;
    const has = v => v !== null && v !== undefined && Number.isFinite(v);

    /** The longest indication allowed for wall thickness T (m). */
    const allowedLength = T => (T <= 0.75 * IN + 1e-9 ? 0.25 * IN : T <= 2.25 * IN + 1e-9 ? T / 3 : 0.75 * IN);

    /**
     * An indication's peak at the file's reference gain (% FSH), or null; Infinity when saturated.
     * item: {sizing, readings, gain}; group: {reference_gain, instrument_gain}.
     */
    function atReference(item, group) {
        const z = item.sizing || {}, r = item.readings || {};
        let recorded = null;   // % at the file's own gain (no soft gain)
        if (z.saturated) recorded = Infinity;
        else if (has(z.peak_amplitude)) recorded = z.peak_amplitude * 10 ** (-(z.base_gain ?? item.gain ?? 0) / 20);
        else if (has(r['A%'])) recorded = r['A%'] * 10 ** (-(item.gain || 0) / 20);
        if (recorded === null) return null;
        const ref = group?.reference_gain, scanned = group?.instrument_gain;
        return has(ref) && ref > 0 && has(scanned) ? recorded * 10 ** ((ref - scanned) / 20) : recorded;
    }

    /**
     * {grade: 'fail' | 'assess' | 'pass', reason} under criteria 'b31.1' / 'b31.3', or null for none.
     * amplitude: % at the reference gain (Infinity: saturated; null: none); reference: the reference
     * level (% FSH); length and thickness T in m (null when not known); format(m) for the reason text.
     */
    function grade(criteria, { amplitude, reference, length, thickness }, format = m => `${(m / IN).toFixed(3)} in`) {
        if (!criteria) return null;
        const amp = amplitude, T = thickness;
        if (!has(amp) && amp !== Infinity) return { grade: 'assess', reason: 'No amplitude to grade - assess it' };
        const db = amp === Infinity ? null : 20 * Math.log10(amp / reference);
        const ampText = amp === Infinity ? 'saturated (over reference)' : `${db >= 0 ? '+' : ''}${db.toFixed(1)} dB to reference (${amp.toFixed(0)} % at reference gain)`;
        const overRef = amp > reference;
        const investigate = criteria === 'b31.1' && amp > 0.2 * reference;
        if (!T || !has(length)) {
            if (!overRef && !investigate) return { grade: 'pass', reason: `${ampText}: not over the reference level` };
            return { grade: 'assess', reason: `${ampText}; ${!T ? 'no part thickness T' : 'no length'} to compare - assess it` };
        }
        const allowed = allowedLength(T);
        // 'Exceeding' with a nanometre's give: a length exactly T/3 (1.5 in / 3 = 0.5 in) mustn't fail on rounding
        const longer = length > allowed + 1e-9;
        const lengthText = `${format(length)} ${longer ? '>' : '≤'} ${format(allowed)} allowed (T ${format(T)})`;
        if (overRef && longer) return { grade: 'fail', reason: `Fails: ${ampText}, ${lengthText}` };
        if (investigate) {
            return { grade: 'assess', reason: `Characterise it: ${ampText}, ${lengthText}. Under B31.1 a crack, lack of fusion or incomplete penetration fails at any length` };
        }
        return { grade: 'pass', reason: `Passes: ${ampText}, ${lengthText}` };
    }

    return { allowedLength, atReference, grade };
})();
