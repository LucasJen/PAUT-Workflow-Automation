// The section menu beside the report editor and Library › Defaults: highlights the section in
// view. updateActiveSection is global so the editor can call it after showing / hiding sections.

function updateActiveSection() {
    const navLinks = document.querySelectorAll('[data-nav-section]');
    const sections = Array.from(document.querySelectorAll('.editor-section')).filter(s => !s.hidden);
    const marker = window.innerHeight * 0.3;
    let current = sections[0];
    sections.forEach(section => {
        if (section.getBoundingClientRect().top <= marker) current = section;
    });
    // At the bottom of the page the last section is current even if short
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) current = sections[sections.length - 1];
    navLinks.forEach(link => link.classList.toggle('active', !!current && link.dataset.navSection === current.dataset.section));
}

window.addEventListener('scroll', updateActiveSection, { passive: true });
window.addEventListener('resize', updateActiveSection);
document.addEventListener('DOMContentLoaded', updateActiveSection);
