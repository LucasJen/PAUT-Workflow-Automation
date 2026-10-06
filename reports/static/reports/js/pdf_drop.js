// Documentation libraries: PDFs dropped anywhere on the page are uploaded through #upload-form.

(function () {
    const form = document.getElementById('upload-form');
    const input = document.getElementById('upload-input');
    if (!form || !input) return;

    const hasFiles = e => e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');

    document.addEventListener('dragover', e => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        document.body.classList.add('drop-target');
    });
    document.addEventListener('dragleave', e => {
        if (e.relatedTarget === null) document.body.classList.remove('drop-target');
    });
    document.addEventListener('drop', e => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        document.body.classList.remove('drop-target');
        input.files = e.dataTransfer.files;
        form.submit();
    });
})();
