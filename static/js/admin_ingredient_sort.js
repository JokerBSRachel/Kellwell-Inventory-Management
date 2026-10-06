// Django's admin fires "formset:added" on each newly cloned inline row.
document.addEventListener('formset:added', (event) => {
    if (event.detail.formsetName !== 'ingredients') return;  // prefix = the FK's related_name

    const row = event.target;
    const newInput = row.querySelector('input[name$="-sort_order"]');
    const group = row.closest('.inline-group');

    // Every other real sort_order input in this inline. Skip the new row itself
    // and Django's hidden "__prefix__" template row that new rows are cloned from.
    const others = [...group.querySelectorAll('input[name$="-sort_order"]')]
        .filter(input => input !== newInput && !input.name.includes('__prefix__'));

    const highest = Math.max(0, ...others.map(input => parseInt(input.value, 10) || 0));
    newInput.value = highest + 10;
});