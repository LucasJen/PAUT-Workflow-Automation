// Guided report editor (From scan files): the report type's sections one at a time, then the scan
// plan, then the preview page. Prev, Next and the step list save the report and go to that step
// (the view redirects to ?step=<key>, or to the preview for 'finish'). Runs after create_report.js
// has shown the type's sections.

(function () {
    const form = document.getElementById('report-form');
    if (!form?.dataset.wizard) return;

    const navTitle = key => document.querySelector(`[data-nav-section="${key}"]`)?.childNodes[0].textContent.trim();
    const steps = Array.from(form.querySelectorAll('.editor-sections > .editor-section'))
        .filter(el => !el.hidden)
        .map(el => {
            const key = el.dataset.section || el.dataset.wizardPanel;
            return { key, el, title: el.dataset.title || navTitle(key) || key };
        });
    steps.push({ key: 'finish', el: null, title: 'Preview & download' });

    const stepInput = document.getElementById('wizard-step');
    const nextButton = document.getElementById('wizard-next');
    const prevButton = document.getElementById('wizard-prev');
    const jumpButton = document.getElementById('wizard-jump');
    const list = document.getElementById('wizard-steps');
    const DONE_STEPS = list.children.length;   // Files and Welds, done before the report existed

    // The step to show: one with a field the server rejected, else the one asked for, else the first
    const invalid = steps.find(step => step.el?.querySelector('.has-error, .is-invalid, .errorlist'));
    let index = invalid ? steps.indexOf(invalid) : Math.max(0, steps.findIndex(step => step.key === stepInput.value));
    if (steps[index].key === 'finish') index = 0;

    function go(key) {
        jumpButton.value = key;
        form.requestSubmit(jumpButton);
    }

    // The step list: done steps, this one, and what's left in each
    const items = steps.map((step, i) => {
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button';
        button.innerHTML = `<span class="wizard-dot">${DONE_STEPS + i + 1}</span> <span class="wizard-label"></span>`;
        button.querySelector('.wizard-label').textContent = step.title;
        button.addEventListener('click', () => { if (i !== index) go(step.key); });
        li.append(button);
        list.append(li);
        return li;
    });

    function missing(step) {
        return step.el && form.classList.contains('fill-marks') && window.FillMarks ? window.FillMarks.missingIn(step.el) : 0;
    }

    function refresh() {
        const step = steps[index];
        items.forEach((li, i) => {
            li.classList.toggle('is-current', i === index);
            li.classList.toggle('is-done', i < index);
            const left = i === steps.length - 1 ? 0 : missing(steps[i]);
            let badge = li.querySelector('.nav-missing');
            if (!left) badge?.remove();
            else {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'nav-missing';
                    badge.title = 'Fields still to fill in this step';
                    li.querySelector('button').append(badge);
                }
                badge.textContent = left;
            }
        });
        const left = missing(step);
        document.getElementById('wizard-status').textContent = !step.el || !form.classList.contains('fill-marks') ? ''
            : left ? `${left} field${left === 1 ? '' : 's'} to fill in` : 'All filled';
        document.getElementById('wizard-status').classList.toggle('is-complete', !left);
    }

    function show() {
        const step = steps[index];
        steps.forEach(s => s.el?.classList.toggle('wizard-off', s !== step));
        stepInput.value = step.key;
        document.getElementById('wizard-count').textContent = `Step ${DONE_STEPS + index + 1} of ${DONE_STEPS + steps.length}`;
        document.getElementById('wizard-title').textContent = step.title;
        const next = steps[index + 1];
        nextButton.value = next.key;
        nextButton.innerHTML = next.key === 'finish'
            ? '<i class="bi bi-eye"></i> Preview &amp; download'
            : 'Next: <span></span> <i class="bi bi-arrow-right"></i>';
        if (next.key !== 'finish') nextButton.querySelector('span').textContent = next.title;
        prevButton.disabled = index === 0;
        refresh();
    }

    prevButton.addEventListener('click', () => { if (index > 0) go(steps[index - 1].key); });
    ['input', 'change', 'click'].forEach(type => form.addEventListener(type, () => setTimeout(refresh)));

    document.getElementById('wizard-plan-reload')?.addEventListener('click', () => {
        for (const img of document.querySelectorAll('.wizard-plan-img')) {
            const url = new URL(img.src, window.location.href);
            url.searchParams.set('t', Date.now());
            img.src = url;
        }
    });

    show();
    // The page opens at this step's top (Prev / Next leave the old scroll position)
    window.scrollTo(0, 0);
})();
