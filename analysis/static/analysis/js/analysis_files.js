// The Files panel's other two views: Browse this PC (drives, usual places, then any folder's
// sub-folders and .nde files - a file is opened where it is, the server records it so the page may
// read it) and New project (a job folder made in the report type's working folder, the files copied
// into it with progress, then Guided Creation from that folder).

window.AnalysisFiles = function ({ page, send, openFile, refreshFiles }) {
    const $ = id => document.getElementById(id);
    const urls = { browse: page.dataset.browseUrl, open: page.dataset.openFileUrl, forget: page.dataset.forgetFileUrl,
                   options: page.dataset.projectOptionsUrl, project: page.dataset.projectUrl, status: page.dataset.projectStatusUrl };
    const views = { files: $('files-view'), pc: $('pc-view'), project: $('project-view') };
    const el = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };
    const note = text => el('p', { className: 'analysis-note', textContent: text });
    const mb = bytes => `${(bytes / 1e6).toFixed(0)} MB`;
    const get = key => { try { return localStorage.getItem(key); } catch { return null; } };
    const set = (key, value) => { try { localStorage.setItem(key, value); } catch { /* not kept */ } };
    let backTo = 'files';

    function showView(name) {
        for (const [key, view] of Object.entries(views)) view.hidden = key !== name;
    }

    // ── Browse this PC ──
    const pc = { path: '', parent: '', picked: new Map() };

    async function browse(path) {
        let data;
        try {
            const response = await fetch(`${urls.browse}?${new URLSearchParams({ path })}`);
            data = await response.json();
            if (!response.ok) throw new Error(data.error || "That folder can't be read.");
        } catch (e) {
            if (path) { set('analysisBrowse', ''); return browse(''); }   // gone since: back to the drives
            $('pc-list').replaceChildren(note(e.message));
            return;
        }
        pc.path = data.path;
        pc.parent = data.parent;
        set('analysisBrowse', data.path);
        // The end of a long path is the part that matters: '…\Job\Scans'
        const shown = data.path.length > 44 ? `…${data.path.slice(-43)}` : data.path;
        $('pc-path').textContent = shown || 'This PC';
        $('pc-path').title = data.path;
        $('pc-up').disabled = !data.path;
        const rows = [];
        for (const place of data.places || []) {
            const b = el('button', { type: 'button', className: 'analysis-file-item', title: place.path },
                el('i', { className: `bi bi-${place.kind === 'drive' ? 'hdd' : 'folder2'}` }), el('span', { className: 'name', textContent: place.name }),
                el('span', { className: 'meta', textContent: place.kind === 'drive' ? 'Drive' : '' }));
            b.addEventListener('click', () => browse(place.path));
            rows.push(b);
        }
        for (const folder of data.folders) {
            const b = el('button', { type: 'button', className: 'analysis-file-item', title: folder.path },
                el('i', { className: 'bi bi-folder' }), el('span', { className: 'name', textContent: folder.name }));
            b.addEventListener('click', () => browse(folder.path));
            rows.push(b);
        }
        for (const file of data.files) {
            const box = el('input', { type: 'checkbox', checked: pc.picked.has(file.path), title: 'Tick for a new project' });
            box.addEventListener('click', e => e.stopPropagation());
            box.addEventListener('change', () => { if (box.checked) pc.picked.set(file.path, file.name); else pc.picked.delete(file.path); showPicked(); });
            const b = el('div', { className: 'analysis-file-item', title: `${file.path}\nClick to open` },
                box, el('i', { className: 'bi bi-file-earmark-bar-graph' }), el('span', { className: 'name', textContent: file.name }),
                el('span', { className: 'meta', textContent: mb(file.size) }));
            b.style.cursor = 'pointer';
            b.addEventListener('click', () => openExternal(file.path));
            rows.push(b);
        }
        if (data.path && !data.folders.length && !data.files.length) rows.push(note('No folders or .nde files here.'));
        $('pc-list').replaceChildren(...rows);
        showPicked();
    }

    function showPicked() {
        const n = pc.picked.size;
        $('pc-picked').textContent = n ? `${n} file${n > 1 ? 's' : ''} ticked` : 'Click a file to open it, or tick files for a project.';
        $('pc-project').disabled = !n;
    }

    /** Records a file from anywhere so the page may read it; returns its path as the server keeps it. */
    async function record(path) {
        return (await send(urls.open, 'POST', { path })).path;
    }

    async function openExternal(path) {
        let real;
        try {
            real = await record(path);
        } catch (e) {
            $('pc-picked').textContent = e.message;
            return;
        }
        showView('files');
        await refreshFiles();
        openFile(real);
    }

    async function forget(path) {
        try { await send(urls.forget, 'POST', { path }); } catch { /* already gone */ }
        refreshFiles();
    }

    $('browse-pc').addEventListener('click', () => { showView('pc'); browse(get('analysisBrowse') || ''); });
    $('pc-back').addEventListener('click', () => showView('files'));
    $('pc-up').addEventListener('click', () => browse(pc.parent));
    $('pc-home').addEventListener('click', () => browse(''));
    $('pc-project').addEventListener('click', async () => {
        try {
            const paths = [];
            for (const path of pc.picked.keys()) paths.push(await record(path));
            backTo = 'pc';
            newProject(paths);
        } catch (e) {
            $('pc-picked').textContent = e.message;
        }
    });

    // ── New project ──
    let project = null;

    async function newProject(paths) {
        showView('project');
        $('project-status').textContent = '';
        $('project-create').disabled = true;
        let data;
        try {
            data = await send(urls.options, 'POST', { paths });
        } catch (e) {
            $('project-files').replaceChildren(note(e.message));
            return;
        }
        project = { picked: new Set(data.files.map(f => f.path)), types: data.types };
        $('project-files').replaceChildren(...data.files.map(file => {
            const box = el('input', { type: 'checkbox', checked: true });
            box.addEventListener('change', () => { if (box.checked) project.picked.add(file.path); else project.picked.delete(file.path); ready(); });
            return el('label', { className: 'analysis-pick', title: file.path }, box, el('span', { className: 'name', textContent: file.name }),
                      el('span', { className: 'meta', textContent: mb(file.size) }));
        }));
        $('project-type').replaceChildren(...data.types.map(t => new Option(t.label, t.key)));
        // What the files look like (weld scans: the weld report), else the type used last
        const last = get('analysisProjectType');
        const pick = [data.suggested_type, last].find(key => data.types.some(t => t.key === key));
        if (pick) $('project-type').value = pick;
        $('project-name').value = data.name;
        showRoot();
        ready();
    }

    function showRoot() {
        const t = project?.types.find(x => x.key === $('project-type').value);
        const box = $('project-root');
        if (!t) { box.textContent = ''; return; }
        if (t.root_ok) box.textContent = `Into ${t.root}`;
        else box.replaceChildren(t.root ? `The working folder ${t.root} isn't there - ` : 'No working folder for this report type yet - ',
                                 el('a', { href: page.dataset.workingFoldersUrl, target: '_blank', textContent: 'set one' }), '.');
        ready();
    }

    function ready() {
        const t = project?.types.find(x => x.key === $('project-type').value);
        $('project-create').disabled = !(project && project.picked.size && t?.root_ok && $('project-name').value.trim());
    }

    $('project-type').addEventListener('change', () => { set('analysisProjectType', $('project-type').value); showRoot(); });
    $('project-name').addEventListener('input', ready);
    $('project-back').addEventListener('click', () => showView(backTo));

    $('project-create').addEventListener('click', async () => {
        const status = $('project-status');
        $('project-create').disabled = true;
        let job;
        try {
            job = await send(urls.project, 'POST', { paths: [...project.picked], type: $('project-type').value, name: $('project-name').value.trim() });
        } catch (e) {
            status.textContent = e.message;
            ready();
            return;
        }
        const bar = el('span', { className: 'analysis-project-progress' }, el('span', { style: 'width: 0%' }));
        status.replaceChildren(bar);
        for (;;) {
            if (job.state === 'done') {
                status.textContent = 'Copied. Starting Guided Creation…';
                location.href = job.next_url;
                return;
            }
            if (job.state === 'error') {
                status.textContent = job.error;
                ready();
                return;
            }
            const fraction = job.total ? job.copied / job.total : 1;
            bar.firstChild.style.width = `${Math.round(fraction * 100)}%`;
            bar.title = `Copying ${job.file}… ${Math.round(fraction * 100)}%`;
            await new Promise(r => setTimeout(r, 400));
            try {
                const response = await fetch(`${urls.status}?${new URLSearchParams({ job: job.job })}`);
                const next = await response.json();
                if (!response.ok) throw new Error(next.error);
                job = { ...next, job: job.job };
            } catch (e) {
                status.textContent = e.message || 'Lost track of the copying.';
                ready();
                return;
            }
        }
    });

    return {
        /** From the file list: a project from the files opened from this PC. */
        newProject: paths => { backTo = 'files'; newProject(paths); },
        forget,
        reset: () => showView('files'),
    };
};
