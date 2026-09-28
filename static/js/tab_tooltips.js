// One shared tooltip element, appended to <body> so no ancestor can clip it.
const tip = document.createElement('div');
tip.className = 'floating-tooltip';
document.body.appendChild(tip);

document.querySelectorAll('.page-tabs [data-tooltip]').forEach(link => {
    link.addEventListener('mouseenter', () => {
        tip.textContent = link.dataset.tooltip;
        const tab = link.getBoundingClientRect();
        const box = tip.getBoundingClientRect();
        const bar = link.closest('.page-tabs').getBoundingClientRect();  // allowed horizontal area

        const EDGE_GAP = 8;  // minimum breathing room from either edge; tune to taste
        const minLeft = bar.left + EDGE_GAP;
        const maxLeft = Math.min(bar.right, document.documentElement.clientWidth) - box.width - EDGE_GAP;

        let left = tab.left + tab.width / 2 - box.width / 2;   // centered over the tab
        left = Math.max(minLeft, Math.min(left, maxLeft));      // clamp: min wins over max if the space is too narrow

        tip.style.left = left + 'px';
        tip.style.top = (tab.top - box.height - 8) + 'px';
        tip.classList.add('visible');
    });
    link.addEventListener('mouseleave', () => tip.classList.remove('visible'));
});

// If the tab bar scrolls sideways, the tooltip would be left floating over the wrong tab.
document.querySelector('.page-tabs')?.addEventListener('scroll', () => tip.classList.remove('visible'));