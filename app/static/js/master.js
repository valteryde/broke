
function openUrlWithArgs(url) {

    // Get the current URL's search parameters
    const currentParams = new URLSearchParams(window.location.search);

    // Create a new URL object
    const newUrl = new URL(url, window.location.origin);

    // Append current search parameters to the new URL
    currentParams.forEach((value, key) => {
        newUrl.searchParams.append(key, value);
    });

    // Navigate to the new URL
    window.location.href = newUrl.toString();
}

(function initGlobalSearch() {
    let debounceTimer = null;

    function getElements() {
        return {
            modal: document.getElementById('global-search-modal'),
            input: document.getElementById('global-search-input'),
            results: document.getElementById('global-search-results'),
            closeBtn: document.getElementById('global-search-close')
        };
    }

    function setResultsHtml(resultsContainer, html) {
        if (resultsContainer) {
            resultsContainer.innerHTML = html;
        }
    }

    function openSearch() {
        const { modal, input, results } = getElements();
        if (!modal || !input || !results) return;

        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        input.value = '';
        setResultsHtml(results, '<div class="global-search-empty">Start typing to search tickets</div>');
        window.setTimeout(() => input.focus(), 0);
    }

    function closeSearch() {
        const { modal } = getElements();
        if (!modal) return;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
    }

    async function performSearch(query) {
        const { results } = getElements();
        if (!results) return;

        if (!query.trim()) {
            setResultsHtml(results, '<div class="global-search-empty">Start typing to search tickets</div>');
            return;
        }

        setResultsHtml(results, '<div class="global-search-loading">Searching...</div>');

        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=12`);
            if (!response.ok) {
                throw new Error('Search request failed');
            }

            const payload = await response.json();
            const rows = payload.results || [];

            if (rows.length === 0) {
                setResultsHtml(results, '<div class="global-search-empty">No tickets found</div>');
                return;
            }

            const html = rows.map((row) => `
                <a class="global-search-item" href="${row.url}">
                    <span class="global-search-item-id">${row.id}</span>
                    <span class="global-search-item-title">${row.title || '(Untitled)'}</span>
                    <span class="global-search-item-meta">${row.project} · ${row.status}</span>
                </a>
            `).join('');

            setResultsHtml(results, html);
        } catch (error) {
            console.error('Global search failed', error);
            setResultsHtml(results, '<div class="global-search-empty">Search is unavailable</div>');
        }
    }

    document.addEventListener('keydown', (event) => {
        const isCommandK = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
        if (isCommandK) {
            event.preventDefault();
            openSearch();
            return;
        }

        if (event.key === 'Escape') {
            const { modal } = getElements();
            if (modal && modal.classList.contains('open')) {
                event.preventDefault();
                closeSearch();
            }
        }
    });

    document.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;

        if (target.matches('[data-search-close="true"]') || target.closest('#global-search-close')) {
            closeSearch();
        }
    });

    document.addEventListener('DOMContentLoaded', () => {
        const { input, closeBtn } = getElements();
        if (!input) return;

        input.addEventListener('input', () => {
            if (debounceTimer) {
                clearTimeout(debounceTimer);
            }
            debounceTimer = setTimeout(() => performSearch(input.value), 150);
        });

        if (closeBtn) {
            closeBtn.addEventListener('click', closeSearch);
        }
    });
})();
