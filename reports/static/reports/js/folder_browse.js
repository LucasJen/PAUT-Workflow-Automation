// Browse… buttons (components/folder_field.html): ask the app to open the Windows folder dialog on
// this computer, then put the picked folder in the box. The dialog can take a moment to appear
// and may open behind the browser; the button says what it's waiting for.

(function () {
    function csrfToken(el) {
        const field = el.closest('form')?.querySelector('[name=csrfmiddlewaretoken]')
            || document.querySelector('[name=csrfmiddlewaretoken]');
        if (field) return field.value;
        const cookie = document.cookie.split('; ').find(c => c.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.split('=')[1]) : '';
    }

    document.addEventListener('click', async e => {
        const button = e.target.closest('[data-browse-for]');
        if (!button) return;
        const input = document.getElementById(button.dataset.browseFor);
        const note = document.querySelector(`[data-browse-note="${button.dataset.browseFor}"]`);
        const label = button.innerHTML;
        const noteText = note ? note.textContent : '';
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Waiting…';
        if (note) note.textContent = 'Pick the folder in the Windows dialog (check the taskbar if it isn\'t in front).';
        try {
            const body = new URLSearchParams({ initial: input.value, title: button.dataset.browseTitle || '' });
            const response = await fetch(button.dataset.browseUrl, {
                method: 'POST', body, headers: { 'X-CSRFToken': csrfToken(button) },
            });
            const data = await response.json();
            if (data.error) {
                if (note) { note.textContent = data.error; note.classList.add('text-danger'); }
                return;
            }
            if (note) { note.textContent = noteText; note.classList.remove('text-danger'); }
            if (data.path) {
                input.value = data.path;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        } catch (err) {
            if (note) { note.textContent = 'The folder dialog didn\'t answer; type the path instead.'; note.classList.add('text-danger'); }
        } finally {
            button.disabled = false;
            button.innerHTML = label;
        }
    });
})();
