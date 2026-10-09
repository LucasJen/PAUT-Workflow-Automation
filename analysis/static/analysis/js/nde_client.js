// Talks to the Analysis API: the file list, a file's groups (SI), frames as typed arrays (with a
// small cache of recent ones) and gate readings, which the server works out with the same code the
// OmniPC checks run.

window.NdeClient = (function () {
    const MAX_FRAMES = 48;
    const frames = new Map();   // key -> {raw: Int16Array, status: Uint8Array|null, lateral, samples}

    async function json(url) {
        const response = await fetch(url);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
        return data;
    }

    function query(params) {
        return new URLSearchParams(params).toString();
    }

    return {
        files: urls => json(urls.files),
        file: (urls, path) => json(`${urls.file}?${query({ path })}`),
        readings: (urls, params) => json(`${urls.readings}?${query(params)}`),

        /** The frame at one scan position: {raw, status, lateral, samples}. */
        async frame(urls, path, group, scan) {
            const key = `${path}|${group}|${scan}`;
            if (frames.has(key)) {
                const hit = frames.get(key);
                frames.delete(key);
                frames.set(key, hit);   // most recently used last
                return hit;
            }
            const response = await fetch(`${urls.frame}?${query({ path, group, scan })}`);
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `Frame request failed (${response.status})`);
            }
            const lateral = +response.headers.get('X-Lateral');
            const samples = +response.headers.get('X-Samples');
            const buffer = await response.arrayBuffer();
            const raw = new Int16Array(buffer, 0, lateral * samples);
            const status = response.headers.get('X-Status') === '1'
                ? new Uint8Array(buffer, lateral * samples * 2, lateral) : null;
            const frame = { raw, status, lateral, samples };
            frames.set(key, frame);
            while (frames.size > MAX_FRAMES) frames.delete(frames.keys().next().value);
            return frame;
        },

        clear() { frames.clear(); },
    };
})();
