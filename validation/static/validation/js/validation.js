// The Validation page: starts a run, follows it live (polling its JSON every second while it runs) and
// shows its result - a verdict, the kit's fingerprints, then each layer with its checks. A check opens to
// its comparisons: what, the independent source's value, the app's value, the rule, and whether they agree.

(function () {
    const page = document.getElementById('validation');
    if (!page) return;
    const $ = id => document.getElementById(id);
    const csrf = () => decodeURIComponent((document.cookie.split('; ').find(c => c.startsWith('csrftoken=')) || '').split('=')[1] || '');
    const urlFor = (template, id) => template.replace('/0', `/${id}`);
    const el = (tag, props = {}, ...children) => {
        const node = Object.assign(document.createElement(tag), props);
        node.append(...children.filter(c => c !== null && c !== undefined && c !== false));
        return node;
    };
    let run = JSON.parse($('shown-run').textContent);
    let timer = null;
    const open = new Set();   // checks opened, kept across live redraws

    const STATUS = {
        running: ['Running…', 'bi-hourglass-split'], passed: ['Passed', 'bi-patch-check-fill'], failed: ['Failed', 'bi-x-octagon-fill'],
        error: ['Stopped by an error', 'bi-exclamation-triangle-fill'], cancelled: ['Stopped', 'bi-stop-circle'],
    };

    function render() {
        $('result-panel').hidden = !run;
        $('cancel-run').hidden = !run || run.status !== 'running';
        $('start-run').hidden = !!run && run.status === 'running';
        if (!run) return;
        const [label, icon] = STATUS[run.status] || [run.status, 'bi-question-circle'];
        $('verdict').className = `val-verdict is-${run.status}`;
        $('verdict').replaceChildren(
            el('i', { className: `bi ${icon}` }),
            el('span', { className: 'val-verdict-label', textContent: `Run #${run.id}: ${label}` }),
            el('span', { className: 'val-verdict-counts', textContent: `${run.passed} passed · ${run.failed} failed` }),
            run.status === 'running' ? null : el('a', { className: 'btn btn-secondary btn-sm val-report', href: urlFor(page.dataset.reportUrl, run.id),
                                                       innerHTML: '<i class="bi bi-file-earmark-word"></i> Report' }));
        const when = new Date(run.created).toLocaleString();
        $('run-meta').replaceChildren(...[
            meta('Started', when), meta('App version', run.version || 'unknown'), meta('Computer', run.computer || '-'),
            meta('Kit', run.kit_path), meta('Kit fingerprint', run.manifest_sha ? `${run.manifest_sha.slice(0, 16)}…` : '-'),
            run.options?.sweep ? meta('Also swept', run.options.sweep) : null].filter(Boolean));
        const body = [kitBlock(run.results.kit)];
        for (const layer of run.results.layers || []) body.push(layerBlock(layer));
        if (run.results.error) body.push(el('p', { className: 'val-error', textContent: run.results.error }));
        $('run-body').replaceChildren(...body);
    }

    const meta = (name, value) => el('span', {}, el('span', { className: 'val-meta-name', textContent: name }), ' ', el('span', { className: 'mono', textContent: value }));

    function progress(fraction, status) {
        return el('div', { className: `val-progress is-${status}` }, el('span', { style: `width:${Math.round((fraction || 0) * 100)}%` }));
    }

    function kitBlock(kit) {
        const bad = (kit.files || []).filter(f => !f.ok);
        const block = el('section', { className: 'val-block' },
            el('header', { className: 'val-block-head' },
                el('span', { className: 'val-layer-id', textContent: 'Kit' }),
                el('strong', { textContent: 'Fingerprints' }),
                el('span', { className: 'val-block-msg', textContent: kit.message || kit.status }),
                kit.status === 'running' ? progress(kit.progress, 'running') : null,
                el('span', { className: 'val-counts' }, count((kit.files || []).length - bad.length, 'ok'), count(bad.length, 'bad'))),
            el('p', { className: 'val-block-q', textContent: 'Every file in the kit matches the fingerprint it was added with, so the evidence is exactly what was recorded and exported.' }));
        for (const f of bad) block.append(el('div', { className: 'val-check is-failed' }, el('i', { className: 'bi bi-x-circle-fill' }), el('span', { className: 'mono', textContent: f.path }), el('span', { textContent: f.reason })));
        return block;
    }

    const count = (n, kind) => el('span', { className: `val-count is-${kind}`, textContent: String(n), title: kind === 'ok' ? 'passed' : 'failed' });

    function layerBlock(layer) {
        const block = el('section', { className: `val-block is-${layer.status.replace(' ', '-')}` },
            el('header', { className: 'val-block-head' },
                el('span', { className: 'val-layer-id', textContent: layer.id }),
                el('strong', { textContent: layer.title }),
                el('span', { className: 'val-block-msg', textContent: (layer.status === 'running' && layer.activity) || layer.message || layer.status }),
                layer.status === 'running' ? progress(layer.progress, 'running') : null,
                layer.status === 'not built' ? null : el('span', { className: 'val-counts' }, count(layer.passed, 'ok'), count(layer.failed, 'bad'))),
            el('p', { className: 'val-block-q' }, layer.question, ' ', el('span', { className: 'val-against', textContent: `Checked against: ${layer.against}.` })));
        if (layer.trace) block.append(el('pre', { className: 'val-trace', textContent: layer.trace }));
        // Failures first, then the rest in the order they ran
        const checks = layer.checks.map((c, i) => [c, i]).sort((a, b) => (a[0].passed - b[0].passed) || (a[1] - b[1]));
        for (const [c, i] of checks) block.append(checkRow(layer.id, c, i));
        return block;
    }

    function checkRow(layerId, c, i) {
        const key = `${layerId}:${i}`;
        const state = c.kind === 'info' ? 'info' : c.passed ? 'passed' : 'failed';
        const icon = { info: 'bi-info-circle', passed: 'bi-check-circle-fill', failed: 'bi-x-circle-fill' }[state];
        const compared = c.items.filter(x => x.ok !== null);
        const agreed = compared.filter(x => x.ok).length;
        const row = el('details', { className: `val-check is-${state}`, open: open.has(key) },
            el('summary', {},
                el('i', { className: `bi ${icon}` }),
                el('span', { className: 'val-check-subject', textContent: c.subject }),
                el('span', { className: 'val-check-title', textContent: c.title }),
                el('span', { className: 'val-check-sum', textContent: c.kind === 'info' ? 'not counted' : `${agreed} of ${compared.length} agree` })));
        row.addEventListener('toggle', () => { if (row.open) open.add(key); else open.delete(key); });
        const table = el('table', { className: 'table data-table val-items' },
            el('thead', {}, el('tr', {}, ...['', 'Compared', `Expected (${c.against})`, 'Measured (the app)', 'Rule'].map(t => el('th', { textContent: t })))),
            el('tbody', {}, ...c.items.map(x => el('tr', { className: x.ok === false ? 'is-bad' : x.ok === null ? 'is-na' : '' },
                el('td', {}, el('i', { className: `bi ${x.ok === null ? 'bi-dash' : x.ok ? 'bi-check-lg' : 'bi-x-lg'}`, title: x.ok === null ? 'Shown, not compared' : '' })),
                el('td', { textContent: x.what }), el('td', { className: 'mono', textContent: x.expected }),
                el('td', { className: 'mono', textContent: x.measured }), el('td', { textContent: x.rule })))));
        row.append(el('div', { className: 'table-wrap' }, table));
        if (c.note) row.append(el('p', { className: 'form-text val-note', textContent: c.note }));
        if (c.pictures?.length) {
            row.append(el('div', { className: 'val-pictures' }, ...c.pictures.map(p => {
                const src = urlFor(page.dataset.pictureUrl, run.id).replace('NAME', encodeURIComponent(p.name));
                return el('figure', {}, el('a', { href: src, target: '_blank', rel: 'noopener' }, el('img', { src, alt: p.caption, loading: 'lazy' })),
                          el('figcaption', { textContent: p.caption }));
            })));
        }
        return row;
    }

    async function poll() {
        clearTimeout(timer);
        if (!run) return;
        const response = await fetch(urlFor(page.dataset.runUrl, run.id));
        if (response.ok) run = await response.json();
        render();
        if (run.status === 'running') timer = setTimeout(poll, 1000);
        else if (new URLSearchParams(location.search).get('run') !== String(run.id)) history.replaceState(null, '', `?run=${run.id}`);
    }

    async function start(body) {
        $('start-run').disabled = true;
        try {
            const response = await fetch(page.dataset.startUrl, { method: 'POST', body: JSON.stringify(body),
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() } });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || response.statusText);
            open.clear();
            run = { id: data.id, status: 'running', passed: 0, failed: 0, created: new Date().toISOString(), options: {}, results: { kit: { status: 'pending' }, layers: [] } };
            history.replaceState(null, '', `?run=${data.id}`);
            poll();
        } catch (e) {
            alert(e.message);
        } finally {
            $('start-run').disabled = false;
        }
    }
    $('start-run').addEventListener('click', () => start({
        layers: [...document.querySelectorAll('input[name=layer]:checked')].map(i => i.value),
        sweep: $('sweep-on').checked ? $('sweep-folder').value : '',
    }));
    $('approve-baseline').addEventListener('click', () => {
        const note = $('approve-note').value.trim();
        if (!note) { $('approve-note').focus(); return; }
        start({ approve: note });
    });
    $('cancel-run').addEventListener('click', () => {
        fetch(urlFor(page.dataset.cancelUrl, run.id), { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
    });

    render();
    if (run && run.status === 'running') poll();
})();
