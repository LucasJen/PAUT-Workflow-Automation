// Report preview: fetch the generated .docx and draw it as pages with docx-preview.

const stage = document.getElementById('preview-stage');
const pages = document.getElementById('preview-pages');
const status = document.getElementById('preview-status');
const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

function showStatus(html, isError = false) {
    status.innerHTML = html;
    status.classList.toggle('error', isError);
    status.hidden = false;
}

async function renderPreview() {
    showStatus('<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Building preview…');
    pages.innerHTML = '';
    try {
        const response = await fetch(stage.dataset.docxUrl, { cache: 'no-store' });
        const type = response.headers.get('Content-Type') || '';
        if (!response.ok || !type.startsWith(DOCX_TYPE)) {
            // e.g. redirected back to the editor because the report has no setups
            throw new Error('The report could not be generated. Go back to the editor and check it has at least one UT setup.');
        }
        const blob = await response.blob();
        await docx.renderAsync(blob, pages, null, {
            inWrapper: true,
            breakPages: true,
            ignoreLastRenderedPageBreak: false,
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

document.getElementById('refresh-preview').addEventListener('click', renderPreview);
renderPreview();
