// Report preview. With Word available the server returns a PDF made by Word, shown in the
// browser's PDF viewer; otherwise the .docx is drawn in the browser with docx-preview.

const stage = document.getElementById('preview-stage');
const status = document.getElementById('preview-status');
const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

function showStatus(html, isError = false) {
    status.innerHTML = html;
    status.classList.toggle('error', isError);
    status.hidden = false;
}

const LOADING = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> ';

// ── Word-made PDF ────────────────────────────────────────────────────────

function renderPdf() {
    const frame = document.getElementById('preview-pdf');
    showStatus(LOADING + 'Word is building the PDF (usually a few seconds)…');
    frame.hidden = true;
    frame.onload = () => {
        status.hidden = true;
        frame.hidden = false;
    };
    // A new URL each time so Refresh always rebuilds the PDF
    frame.src = `${stage.dataset.pdfUrl}?t=${Date.now()}`;
}

// ── In-browser .docx preview (no Word) ──────────────────────────────────

async function renderDocx() {
    const pages = document.getElementById('preview-pages');
    showStatus(LOADING + 'Building preview…');
    pages.innerHTML = '';
    try {
        const response = await fetch(stage.dataset.docxUrl, { cache: 'no-store' });
        const type = response.headers.get('Content-Type') || '';
        if (!response.ok || !type.startsWith(DOCX_TYPE)) {
            // e.g. redirected back to the editor because the report has no setups
            throw new Error('The report could not be generated. Go back to the editor and check it has at least one UT setup.');
        }
        await docx.renderAsync(await response.blob(), pages, null, {
            inWrapper: true,
            breakPages: true,
            // The template carries Word's cached page positions from the reference report;
            // breaking there puts pages in the wrong places, so only real breaks are used
            ignoreLastRenderedPageBreak: true,
            renderHeaders: true,
            renderFooters: true,
            renderFootnotes: true,
            experimental: true,
            useBase64URL: true,
        });
        status.hidden = true;
    } catch (err) {
        showStatus(`<i class="bi bi-exclamation-triangle"></i> ${err.message || 'The preview could not be shown.'}`, true);
    }
}

const render = stage.dataset.pdfUrl ? renderPdf : renderDocx;
document.getElementById('refresh-preview').addEventListener('click', render);
render();
