// The assistant chat: sends a question and shows the answer as it streams in (newline-delimited
// JSON events from assistant/views.py ask: conversation, status, step, text, done, error).
(function () {
    const form = document.getElementById('chat-form');
    if (!form) return;
    const list = document.getElementById('chat-messages');
    const textarea = form.querySelector('textarea[name=question]');
    const button = form.querySelector('button[type=submit]');
    const conversationInput = form.querySelector('input[name=conversation]');

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text) node.textContent = text;
        return node;
    }

    function scrollDown() {
        list.scrollTop = list.scrollHeight;
    }

    function addSources(bot, sources) {
        if (!sources || !sources.length) return;
        const box = el('div', 'chat-sources');
        box.appendChild(el('span', '', 'Sources:'));
        sources.forEach(s => {
            const a = el('a', '', s.label);
            a.href = s.url;
            a.target = '_blank';
            a.rel = 'noopener';
            box.appendChild(a);
        });
        bot.appendChild(box);
    }

    // A new conversation joins the list on the left (a reload would list it too)
    function addToList(id, title) {
        const aside = document.querySelector('.chat-list');
        const url = form.dataset.conversationUrl.replace('/0/', `/${id}/`);
        if (!aside || aside.querySelector(`a[href="${url}"]`)) return;
        aside.querySelector('p.form-text')?.remove();
        aside.querySelectorAll('.chat-list-item.active').forEach(a => a.classList.remove('active'));
        const item = el('a', 'chat-list-item active');
        item.href = url;
        item.title = title || '';
        item.append(el('span', 'chat-list-title', title || 'New chat'), el('span', 'chat-list-date', 'Now'));
        aside.firstElementChild.after(item);
    }

    async function ask(question) {
        document.getElementById('chat-empty')?.remove();
        list.appendChild(el('div', 'chat-msg chat-user', question));
        const bot = el('div', 'chat-msg chat-bot');
        const steps = el('ul', 'chat-live-steps');
        const status = el('div', 'chat-status', 'Sending…');
        const answer = el('div', 'chat-answer chat-streaming');
        bot.append(status, steps, answer);
        list.appendChild(bot);
        scrollDown();

        const body = new FormData(form);
        body.set('question', question);
        textarea.value = '';
        textarea.disabled = button.disabled = true;
        try {
            const response = await fetch(form.dataset.url, {method: 'POST', body});
            if (!response.ok || !response.body) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `The server answered ${response.status}.`);
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            for (;;) {
                const {value, done} = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, {stream: true});
                let newline;
                while ((newline = buffer.indexOf('\n')) >= 0) {
                    const line = buffer.slice(0, newline).trim();
                    buffer = buffer.slice(newline + 1);
                    if (line) handle(JSON.parse(line), {bot, steps, status, answer});
                }
            }
        } catch (error) {
            status.textContent = '';
            bot.classList.add('chat-error');
            answer.textContent = error.message || 'Something went wrong.';
        } finally {
            textarea.disabled = button.disabled = false;
            textarea.focus();
            scrollDown();
        }
    }

    function handle(event, parts) {
        const {bot, steps, status, answer} = parts;
        switch (event.type) {
            case 'conversation':
                if (!conversationInput.value) {
                    conversationInput.value = event.id;
                    // The new chat gets its own address, so a reload or the list opens it
                    history.replaceState(null, '', form.dataset.conversationUrl.replace('/0/', `/${event.id}/`));
                }
                break;
            case 'status':
                status.textContent = event.text;
                break;
            case 'step':
                steps.appendChild(el('li', '', event.text));
                break;
            case 'text':
                status.textContent = '';
                answer.textContent += event.text;
                break;
            case 'done': {
                status.remove();
                answer.classList.remove('chat-streaming');
                answer.innerHTML = event.html;   // rendered server-side from Markdown with raw HTML disabled
                if (steps.children.length) {
                    const details = el('details', 'chat-steps');
                    details.appendChild(el('summary', '', `${steps.children.length} look-up${steps.children.length === 1 ? '' : 's'}`));
                    steps.className = '';
                    details.appendChild(steps);
                    bot.insertBefore(details, answer);
                } else {
                    steps.remove();
                }
                addSources(bot, event.sources);
                bot.appendChild(el('div', 'chat-cost', event.model + (event.cost ? ` · ${event.cost}` : '')));
                const title = document.getElementById('chat-title');
                if (title && event.title) title.textContent = event.title;
                addToList(event.conversation, event.title);
                const cost = document.getElementById('chat-cost');
                if (cost && event.conversation_cost) cost.textContent = event.conversation_cost;
                break;
            }
            case 'error':
                status.textContent = '';
                bot.classList.add('chat-error');
                answer.classList.remove('chat-streaming');
                answer.textContent = event.text;
                break;
        }
        scrollDown();
    }

    form.addEventListener('submit', e => {
        e.preventDefault();
        const question = textarea.value.trim();
        if (question && !button.disabled) ask(question);
    });
    textarea.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.requestSubmit();
        }
    });
    scrollDown();
})();
