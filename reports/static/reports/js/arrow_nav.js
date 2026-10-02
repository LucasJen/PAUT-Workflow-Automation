// Arrow keys move between fields, like Excel, in any form marked data-arrow-nav (the report
// editor, Library › Defaults, the setup and scan plan editors). The next field is the nearest
// one on screen in the arrow's direction, so it works for every layout: field grids, the weld
// grids, tables and blocks. Arrows keep their own job inside a field: Left / Right leave a text
// field only from its start / end, Up / Down leave a text box only from its first / last line,
// and dropdowns, dates, numbers and suggestion lists keep Up / Down.

(function () {
    const FIELDS = 'input, select, textarea';
    const SKIPPED_TYPES = new Set(['hidden', 'file', 'submit', 'button', 'reset', 'image']);
    const KEEP_UP_DOWN_TYPES = new Set(['date', 'datetime-local', 'month', 'week', 'time', 'number', 'range']);
    const TEXT_TYPES = new Set(['text', 'search', 'email', 'url', 'tel', 'password', '']);
    const ROW_TOLERANCE = 8;   // px: fields whose tops are this close are on the same row

    function usable(el) {
        if (el.disabled || el.readOnly || el.tabIndex < 0) return false;
        if (el.tagName === 'INPUT' && SKIPPED_TYPES.has(el.type)) return false;
        if (el.closest('[hidden], template')) return false;
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
    }

    function isText(el) {
        return el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && TEXT_TYPES.has(el.type));
    }

    // Whether this arrow should leave the field rather than do its usual job inside it
    function leaves(el, key) {
        const vertical = key === 'ArrowUp' || key === 'ArrowDown';
        if (el.tagName === 'SELECT') return !vertical;
        if (el.tagName === 'INPUT') {
            if (el.type === 'checkbox' || el.type === 'radio') return true;
            if (KEEP_UP_DOWN_TYPES.has(el.type) || el.hasAttribute('list')) {
                if (vertical) return false;
                if (!isText(el)) return true;   // dates / numbers: Left / Right leave
            }
        }
        if (!isText(el)) return true;
        const { selectionStart: start, selectionEnd: end, value } = el;
        if (start === null) return true;
        if (key === 'ArrowLeft') return start === 0 && end === 0;
        if (key === 'ArrowRight') return start === value.length;
        if (el.tagName !== 'TEXTAREA') return true;   // single line: Up / Down always leave
        if (key === 'ArrowUp') return !value.slice(0, start).includes('\n');
        return !value.slice(end).includes('\n');
    }

    const centre = box => ({ x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 });

    // The nearest row of fields above / below `from`, then the one closest horizontally. Fields
    // in the same column come first, so Down past an N/A cell stays in its column.
    function vertical(from, candidates, down) {
        const here = from.getBoundingClientRect();
        let ahead = candidates.map(el => ({ el, box: el.getBoundingClientRect() }))
            .filter(({ box }) => down ? box.top >= here.bottom - 4 : box.bottom <= here.top + 4);
        if (!ahead.length) return null;
        const column = ahead.filter(({ box }) => box.left < here.right && box.right > here.left);
        if (column.length) ahead = column;
        const edge = down ? Math.min(...ahead.map(c => c.box.top)) : Math.max(...ahead.map(c => c.box.bottom));
        const row = ahead.filter(({ box }) => Math.abs((down ? box.top : box.bottom) - edge) <= ROW_TOLERANCE);
        const x = centre(here).x;
        row.sort((a, b) => Math.abs(centre(a.box).x - x) - Math.abs(centre(b.box).x - x));
        return row[0].el;
    }

    // The nearest field beside `from` on its row; at the row's end, on to the next / previous row
    function horizontal(from, candidates, right) {
        const here = from.getBoundingClientRect();
        const beside = candidates.map(el => ({ el, box: el.getBoundingClientRect() }))
            .filter(({ box }) => box.top < here.bottom && box.bottom > here.top)
            .filter(({ box }) => right ? box.left >= here.right - 2 : box.right <= here.left + 2);
        if (beside.length) {
            beside.sort((a, b) => right ? a.box.left - b.box.left : b.box.right - a.box.right);
            return beside[0].el;
        }
        const next = vertical(from, candidates, right);
        if (!next) return null;
        // The first field of the next row / the last of the previous one
        const top = next.getBoundingClientRect().top;
        const row = candidates.filter(el => Math.abs(el.getBoundingClientRect().top - top) <= ROW_TOLERANCE);
        row.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
        return right ? row[0] : row[row.length - 1];
    }

    document.addEventListener('keydown', event => {
        const { key } = event;
        if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)) return;
        if (event.ctrlKey || event.altKey || event.shiftKey || event.metaKey || event.defaultPrevented) return;
        const el = event.target;
        const form = el.closest?.('form[data-arrow-nav]');
        if (!form || !el.matches(FIELDS) || !leaves(el, key)) return;
        const candidates = Array.from(form.querySelectorAll(FIELDS)).filter(c => c !== el && usable(c));
        const target = key === 'ArrowUp' || key === 'ArrowDown'
            ? vertical(el, candidates, key === 'ArrowDown')
            : horizontal(el, candidates, key === 'ArrowRight');
        if (!target) return;
        event.preventDefault();
        target.focus();
        if (isText(target)) target.select?.();
        target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    });
})();
