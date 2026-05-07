/*
 * Generic List class with modular filtering, grouping, and rendering support.
 *
 * Optional `virtualScroll: true | { minItems?: number, overscan?: number }` window-scroll
 * virtualization for large lists (reduces DOM size). Default minItems threshold is 48.
 *
 * Usage:
 * const list = new List('container-id', {
 *     filters: { ... },
 *     groups: { ... },
 *     renderer: (element) => HTMLElement | string,
 *     quickActions: { ... },
 *     defaultGroupBy: 'none',
 *     onCreate: () => void,
 *     onUpdate: (item, field, value) => void
 * });
 */

class List {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`List container #${containerId} not found`);
            return;
        }
        this.container.classList.add('list-container');
        this.elements = [];
        this.filteredElements = [];
        this.options = options;
        /** @type {{ minItems: number, overscan: number } | null} */
        this._virtualScrollCfg = List._normalizeVirtualScrollOption(options.virtualScroll);

        // Configuration
        this.filtersConfig = options.filters || {};
        this.groupsConfig = options.groups || {};
        this.renderer = options.renderer || this.defaultRenderer;
        this.quickActions = options.quickActions || {};

        this.activeFilters = {};
        this.activeFilterChips = {};
        this.currentGroupBy = options.defaultGroupBy || options.groupBy?.default || 'none';
        this.syncUrlState = options.syncUrlState !== false;
        this.getInitialState = typeof options.getInitialState === 'function' ? options.getInitialState : null;
        this.onStateChange = typeof options.onStateChange === 'function' ? options.onStateChange : null;
        // Note: supporting old groupBy.default structure for backward compat if needed, but we are updating call sites.

        // Callbacks
        this.onCreate = options.onCreate || null;
        this.onDelete = options.onDelete || null;
        this.onCreateLabel = options.onCreateLabel || 'Add';
        this.onClearFilters = options.onClearFilters || null;
        this.onClearFiltersLabel = options.onClearFiltersLabel || 'Clear Filters';

        // Create wrapper structure
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'list-wrapper';
        this.container.parentNode.insertBefore(this.wrapper, this.container);

        // Create filter bar if filters or groupBy are configured
        if (Object.keys(this.filtersConfig).length > 0 || Object.keys(this.groupsConfig).length > 0) {
            this.filterBar = this.createFilterBar();
            this.wrapper.appendChild(this.filterBar);
        }

        this.wrapper.appendChild(this.container);

        // Selection state
        this.selectedIndex = -1;
        this.renderedItems = []; // Array of { element, domNode }

        /** @type {boolean} */
        this._virtualActive = false;
        /** Collapsed groups when virtual scrolling (group keys from grouping config). */
        this.collapsedGroupKeys = new Set();
        this._vsBound = false;
        this._vsRafQueued = false;
        this.virtualFlatElements = [];
        this.virtualRows = [];
        this.virtualPrefix = [];
        this.virtualTotalHeight = 0;
        /** Pixel offset within the scroll track for each item in virtualFlatElements (prefix Y at row start). */
        this.virtualItemOffsetY = [];
        this._vsMeasuredItemHeight = 0;
        this._vsMeasuredHeaderHeight = 0;
        this._vsMeasureRecursing = false;
        this._vsItemHeightDefault = 82;
        this._vsHeaderHeightDefault = 52;
        this._vsOverscan = 8;

        // Action callback
        this.onUpdate = options.onUpdate || (() => { });

        this.initShortcuts();

        this.hydrateInitialState();

        if (this._virtualScrollCfg) {
            this._vsOverscan = this._virtualScrollCfg.overscan;
        }

        this.applyFilters();
    }

    hydrateInitialState() {
        const initialState = this.getInitialState ? this.getInitialState() : null;
        const hasCustomState = Boolean(initialState && typeof initialState === 'object');

        if (hasCustomState) {
            if (initialState.groupBy && this.groupsConfig[initialState.groupBy]) {
                this.currentGroupBy = initialState.groupBy;
            }

            if (initialState.filters && typeof initialState.filters === 'object') {
                Object.keys(this.filtersConfig).forEach(filterType => {
                    if (!Object.prototype.hasOwnProperty.call(initialState.filters, filterType)) {
                        return;
                    }

                    const restoredValue = initialState.filters[filterType];
                    if (restoredValue === null || restoredValue === undefined || restoredValue === '') {
                        return;
                    }

                    this.activeFilters[filterType] = restoredValue;
                    this.updateFilterChipFromValue(filterType, restoredValue);
                });
            }
        }

        if (!this.syncUrlState) {
            return;
        }

        const urlParams = new URLSearchParams(window.location.search);
        Object.keys(this.filtersConfig).forEach(filterType => {
            const paramKey = `filter_${filterType}`;
            if (!urlParams.has(paramKey)) {
                return;
            }

            const paramValue = urlParams.get(paramKey);
            const config = this.filtersConfig[filterType];

            if (config.getValueFromOption) {
                const value = config.getValueFromOption(paramValue);
                value.optionValue = paramValue;
                value.optionLabel = paramValue;
                this.activeFilters[filterType] = value;
                this.updateFilterChip(filterType, paramValue);
                return;
            }

            if (filterType === 'search') {
                this.activeFilters[filterType] = paramValue;
                return;
            }

            const values = paramValue.split(',');
            this.activeFilters[filterType] = values;
            this.updateFilterChip(filterType, values.join(', '));
        });

        if (urlParams.has('group')) {
            const urlGroupBy = urlParams.get('group');
            if (urlGroupBy && this.groupsConfig[urlGroupBy]) {
                this.currentGroupBy = urlGroupBy;
            }
        }
    }

    updateFilterChipFromValue(filterType, value) {
        const config = this.filtersConfig[filterType];
        if (!config || filterType === 'search') {
            return;
        }

        if (Array.isArray(value)) {
            if (value.length > 0) {
                this.updateFilterChip(filterType, value.join(', '));
            }
            return;
        }

        if (typeof value === 'object' && value.optionLabel) {
            this.updateFilterChip(filterType, value.optionLabel);
            return;
        }

        this.updateFilterChip(filterType, String(value));
    }

    emitStateChange() {
        if (!this.onStateChange) {
            return;
        }

        this.onStateChange({
            groupBy: this.currentGroupBy,
            filters: this.activeFilters
        }, this);
    }

    defaultRenderer(element) {
        const div = document.createElement('div');
        div.textContent = JSON.stringify(element);
        return div;
    }

    initShortcuts() {
        if (!window.shortcuts) return;

        // Only trigger shortcuts if mouse is hovering over the list area
        const target = () => {
            if (!this.wrapper || !this.wrapper.matches(':hover')) {
                return null;
            }

            // Find the currently selected item
            let children = this.wrapper.querySelectorAll('.list-element');
            for (let i = 0; i < children.length; i++) {
                if (children[i].matches(':hover')) {
                    return children[i];
                }
            }

            return null;
        };

        window.shortcuts.register('j', (target, e) => this.moveSelection(1), 'Next Item', false, target);
        window.shortcuts.register('k', (target, e) => this.moveSelection(-1), 'Previous Item', false, target);
        window.shortcuts.register('Enter', (target, e) => this.openSelectedItem(), 'Open Item', false, target);

        if (this.onDelete) {
            const deleteAction = (target, e) => {
                if (this.selectedIndex >= 0 && this.renderedItems[this.selectedIndex]) {
                    const item = this.renderedItems[this.selectedIndex].element;
                    if (confirm('Are you sure you want to delete this item?')) {
                        this.onDelete(item);
                    }
                }
            };
            window.shortcuts.register('d', deleteAction, 'Delete Item', false, target);
            window.shortcuts.register('Backspace', deleteAction, 'Delete Item', false, target);
        }

        // Register configured quick actions
        Object.entries(this.quickActions).forEach(([key, action]) => {
            window.shortcuts.register(key, (target, e) => this.triggerQuickAction(key, target), action.name, false, target);
        });
    }

    moveSelection(direction) {
        if (this.renderedItems.length === 0) return;

        const oldIndex = this.selectedIndex;
        let newIndex = this.selectedIndex + direction;

        if (newIndex < 0) newIndex = 0;
        if (newIndex >= this.renderedItems.length) newIndex = this.renderedItems.length - 1;

        if (oldIndex !== newIndex) {
            this.setSelection(newIndex);
        }
    }

    setSelection(index, scrollToItem = true) {
        const prev = this.renderedItems[this.selectedIndex];
        if (prev && prev.domNode) {
            prev.domNode.classList.remove('selected');
        }

        this.selectedIndex = index;

        if (this.selectedIndex < 0 || !this.renderedItems[this.selectedIndex]) {
            return;
        }

        if (this._virtualActive && scrollToItem) {
            this.scrollItemIndexIntoView(this.selectedIndex);
            this._runVirtualSlice(false);
        }

        const node = this.renderedItems[this.selectedIndex].domNode;
        if (node) {
            node.classList.add('selected');
            if (scrollToItem && !this._virtualActive) {
                node.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }
    }

    /**
     * Scroll the page so the flat item at index is in view (window-virtualized lists).
     */
    scrollItemIndexIntoView(itemIndex) {
        if (itemIndex < 0 || !this.virtualItemOffsetY || itemIndex >= this.virtualItemOffsetY.length) {
            return;
        }
        const y = this.virtualItemOffsetY[itemIndex];
        const anchor = this._vsAnchor;
        if (!anchor) {
            return;
        }
        const anchorTopDoc = anchor.getBoundingClientRect().top + window.scrollY;
        window.scrollTo({
            top: anchorTopDoc + y - 96,
            behavior: 'auto'
        });
    }

    openSelectedItem() {
        if (this.selectedIndex >= 0 && this.renderedItems[this.selectedIndex]) {
            const item = this.renderedItems[this.selectedIndex].element;
            if (item.onClick) {
                item.onClick(item);
            }
        }
    }

    triggerQuickAction(actionKey, target) {
        const action = this.quickActions[actionKey];
        if (!action) return;

        this.selectedIndex = this.renderedItems.findIndex(item => item.domNode === target);
        this.setSelection(this.selectedIndex);

        if (this.selectedIndex < 0 || !this.renderedItems[this.selectedIndex]) return;

        const item = this.renderedItems[this.selectedIndex].element;
        action.handler(this, item);
    }

    handleUpdate(item, field, value, isToggle = false) {
        // Optimistic update logic moved to specific list configs?
        // Actually, the generic list doesn't know how to update the item object deeply
        // (like arrays etc), so it relies on the caller or the specific logic handled in handler.
        // BUT, `lists.js` originally had logic for updating item state (assignees array etc).
        // This should probably be done inside the `handler` or `onUpdate`?
        // Let's assume the `handler` in QuickActions takes care of mutating the item if needed,
        // OR we provide a helper here.

        // Original lists.js had this logic:
        if (field === 'status') item.status = value;
        if (field === 'priority') item.urgency = value; // Coupled to 'urgency' prop

        if (field === 'assignees' && isToggle) {
            const idx = item.assignees.indexOf(value);
            if (idx > -1) item.assignees.splice(idx, 1);
            else item.assignees.push(value);
        }

        if (field === 'labels' && isToggle) {
            // For value {name, color}
            // We need to be careful. Generic list shouldn't know about 'labels' structure?
            // Ideally this logic moves to the Specific Configs if possible, or we keep it here if commonly used.
            // Given the constraints, I'll keep this simple update logic here BUT it might be risky if data shapes differ.
            // However, Error list uses similar shapes (labels, status).
            if (value && typeof value === 'object' && value.name) {
                const idx = item.labels.findIndex(l => l.text === value.name);
                if (idx > -1) item.labels.splice(idx, 1);
                else item.labels.push({ text: value.name, color: value.color });
            }
        }

        // Re-apply filters
        const selectionId = item.id;
        this.applyFilters();

        const newIndex = this.renderedItems.findIndex(i => i.element.id === selectionId);
        if (newIndex > -1) this.setSelection(newIndex, false);

        this.onUpdate(item, field, value, isToggle);
    }

    // Get submenu options for each filter type
    getFilterOptions(filterType) {
        const config = this.filtersConfig[filterType];
        if (config && config.getOptions) {
            return config.getOptions(this);
        }
        return [];
    }

    createFilterBar() {
        const filterBar = document.createElement('div');
        filterBar.className = 'list-filter-bar';

        // Top row: search and add filter button
        const filterOptionsRow = document.createElement('div');
        filterOptionsRow.className = 'list-filter-options';

        // Search bar (if configured)
        if (this.filtersConfig.search) {
            const searchWrapper = document.createElement('div');
            searchWrapper.className = 'list-search-wrapper';

            const searchIcon = document.createElement('i');
            searchIcon.className = 'ph ph-magnifying-glass';

            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.className = 'list-search-input';
            searchInput.placeholder = this.filtersConfig.search.placeholder || 'Search...';
            searchInput.value = this.activeFilters.search || '';

            searchInput.addEventListener('input', () => {
                this.activeFilters.search = searchInput.value;
                this.applyFilters();
            });

            searchWrapper.appendChild(searchIcon);
            searchWrapper.appendChild(searchInput);
            filterOptionsRow.appendChild(searchWrapper);
        }

        // Add filter dropdown
        const addFilterWrapper = document.createElement('div');
        addFilterWrapper.className = 'list-add-filter-wrapper';

        const addFilterBtn = document.createElement('button');
        addFilterBtn.className = 'list-add-filter-btn';
        addFilterBtn.innerHTML = '<i class="ph ph-funnel"></i> <span>Add filter</span> <i class="ph ph-caret-down"></i>';

        addFilterWrapper.appendChild(addFilterBtn);
        filterOptionsRow.appendChild(addFilterWrapper);

        // Group by dropdown
        if (Object.keys(this.groupsConfig).length > 0) {
            const groupByWrapper = document.createElement('div');
            groupByWrapper.className = 'list-group-by-wrapper';

            const groupByBtn = document.createElement('button');
            groupByBtn.className = 'list-group-by-btn';
            this.groupByBtn = groupByBtn;
            this.updateGroupByButtonLabel();

            groupByWrapper.appendChild(groupByBtn);
            filterOptionsRow.appendChild(groupByWrapper);

            // Build group by dropdown items
            const groupByItems = Object.keys(this.groupsConfig).map(groupType => {
                const conf = this.groupsConfig[groupType];
                return {
                    label: conf.label || groupType,
                    icon: conf.icon || 'ph-list',
                    onClick: () => {
                        this.setGroupBy(groupType);
                    }
                };
            });

            this.groupByDropdown = new Dropdown(groupByBtn, {
                items: groupByItems,
                closeOnClick: true
            });
        }

        if (this.onClearFilters) {
            const clearFiltersButton = document.createElement('button');
            clearFiltersButton.className = 'list-clear-filters-btn';
            clearFiltersButton.innerHTML = `<span><i class="ph ph-x-circle"></i> ${this.onClearFiltersLabel}</span>`;
            clearFiltersButton.addEventListener('click', () => {
                this.onClearFilters(this);
            });
            filterOptionsRow.appendChild(clearFiltersButton);
        }

        if (this.onCreate) {
            const createButton = document.createElement('button');
            createButton.className = 'list-create-btn';
            createButton.innerHTML = `<span> <i class="ph ph-plus"></i> ${this.onCreateLabel || 'Add'} </span>`;

            createButton.addEventListener('click', () => {
                this.onCreate();
            });

            filterOptionsRow.appendChild(createButton);
        }

        // Bottom row: Active filters container (chips)
        this.activeFiltersContainer = document.createElement('div');
        this.activeFiltersContainer.className = 'list-active-filters';

        // Build dropdown items with submenus for each filter type
        const dropdownItems = [];
        Object.keys(this.filtersConfig).forEach(filterType => {
            if (filterType !== 'search') {
                const config = this.filtersConfig[filterType];
                dropdownItems.push({
                    label: config.label,
                    icon: config.icon,
                    getSubmenuItems: () => {
                        const options = this.getFilterOptions(filterType);
                        return options.map(opt => ({
                            ...opt,
                            selected: this.isOptionSelected(filterType, opt.value)
                        }));
                    },
                    onSubmenuClick: (item) => {
                        this.toggleFilterOption(filterType, item);
                    }
                });
            }
        });

        // Create the dropdown
        this.filterDropdown = new Dropdown(addFilterBtn, {
            items: dropdownItems,
            closeOnClick: true
        });

        filterBar.appendChild(filterOptionsRow);
        filterBar.appendChild(this.activeFiltersContainer);

        return filterBar;
    }

    isOptionSelected(filterType, value) {
        const filter = this.activeFilters[filterType];
        if (!filter) return false;

        // Special handling for dateRange stored as object {from, to}
        // Actually, the original stored {optionValue, optionLabel, ...} in dateRange
        // Let's stick to the generic approach:

        // If filter is an object and has optionValue (like DateRange in original)
        if (filter.optionValue) {
            return filter.optionValue === value;
        }

        if (Array.isArray(filter)) {
            return filter.includes(value);
        }

        return filter === value;
    }

    toggleFilterOption(filterType, option) {
        const config = this.filtersConfig[filterType];

        // Check if it's single select or "date range" style (helper in config?)
        // Or if getValueFromOption is present
        if (config.getValueFromOption) {
            // Single select / Replace mode
            if (this.activeFilters[filterType]?.optionValue === option.value) {
                this.removeFilter(filterType);
            } else {
                const value = config.getValueFromOption(option.value);
                value.optionValue = option.value;
                value.optionLabel = option.label;
                this.activeFilters[filterType] = value;
                this.updateFilterChip(filterType, option.label);
            }
        } else {
            // Default Multi-select behavior
            if (!this.activeFilters[filterType]) {
                this.activeFilters[filterType] = [];
            }

            const index = this.activeFilters[filterType].indexOf(option.value);
            if (index > -1) {
                this.activeFilters[filterType].splice(index, 1);
                if (this.activeFilters[filterType].length === 0) {
                    this.removeFilter(filterType);
                    return;
                }
            } else {
                this.activeFilters[filterType].push(option.value);
            }

            this.updateFilterChip(filterType, this.activeFilters[filterType].join(', '));
        }

        this.applyFilters();
    }

    updateFilterChip(filterType, displayValue) {
        if (this.activeFilterChips[filterType]) {
            this.activeFilterChips[filterType].remove();
        }

        const config = this.filtersConfig[filterType];

        const chip = document.createElement('div');
        chip.className = 'list-filter-chip';
        chip.dataset.filterType = filterType;

        const icon = document.createElement('i');
        icon.className = `ph ${config.icon}`;

        const label = document.createElement('span');
        label.className = 'list-filter-chip-label';
        label.textContent = config.label;

        const value = document.createElement('span');
        value.className = 'list-filter-chip-value-text';
        value.textContent = displayValue;

        const removeBtn = document.createElement('button');
        removeBtn.className = 'list-filter-chip-remove';
        removeBtn.innerHTML = '<i class="ph ph-x"></i>';
        removeBtn.addEventListener('click', () => {
            this.removeFilter(filterType);
        });

        chip.appendChild(icon);
        chip.appendChild(label);
        chip.appendChild(value);
        chip.appendChild(removeBtn);

        this.activeFiltersContainer.appendChild(chip);
        this.activeFilterChips[filterType] = chip;
    }

    removeFilter(filterType) {
        delete this.activeFilters[filterType];

        if (this.activeFilterChips[filterType]) {
            this.activeFilterChips[filterType].remove();
            delete this.activeFilterChips[filterType];
        }

        this.applyFilters();
    }

    extractLabels() {
        const labelsMap = new Map();
        this.elements.forEach(el => {
            if (el.labels) {
                el.labels.forEach(label => {
                    if (!labelsMap.has(label.text)) {
                        labelsMap.set(label.text, label);
                    }
                });
            }
        });
        return Array.from(labelsMap.values());
    }

    extractAssignees() {
        const assignees = new Set();
        this.elements.forEach(el => {
            if (el.assignees) {
                el.assignees.forEach(a => assignees.add(a));
            }
        });
        return Array.from(assignees).sort();
    }

    updateGroupByButtonLabel() {
        if (this.groupByBtn) {
            const groupType = this.groupsConfig[this.currentGroupBy];
            const label = groupType?.label || 'Group';
            this.groupByBtn.innerHTML = `<i class="ph ${groupType?.icon || 'ph-list'}"></i> <span>Group: ${label}</span> <i class="ph ph-caret-down"></i>`;
        }
    }

    setGroupBy(groupType) {
        this.currentGroupBy = groupType;
        this.updateGroupByButtonLabel();
        this.render();

        if (this.syncUrlState) {
            const url = new URL(window.location);
            if (groupType === 'none') {
                url.searchParams.delete('group');
            } else {
                url.searchParams.set('group', groupType);
            }
            window.history.replaceState({}, '', url);
        }

        this.emitStateChange();

    }

    groupElements(elements) {
        const groupType = this.groupsConfig[this.currentGroupBy];
        if (!groupType || this.currentGroupBy === 'none') {
            return null;
        }

        const groups = new Map();

        elements.forEach(element => {
            const key = groupType.getGroupKey(element);
            if (!groups.has(key)) {
                groups.set(key, []);
            }
            groups.get(key).push(element);
        });

        // Sort groups
        let sortedKeys;
        if (groupType.order) {
            sortedKeys = [...groups.keys()].sort((a, b) => {
                const indexA = groupType.order.indexOf(a);
                const indexB = groupType.order.indexOf(b);
                if (indexA === -1 && indexB === -1) return 0;
                if (indexA === -1) return 1;
                if (indexB === -1) return -1;
                return indexA - indexB;
            });
        } else {
            sortedKeys = [...groups.keys()].sort();
        }

        return sortedKeys.map(key => ({
            key,
            label: groupType.getGroupLabel(key),
            elements: groups.get(key)
        }));
    }

    clearAllFilters() {
        this.activeFilters = {};
        Object.keys(this.activeFilterChips).forEach(filterType => {
            if (this.activeFilterChips[filterType]) {
                this.activeFilterChips[filterType].remove();
            }
        });
        this.activeFilterChips = {};
        this.applyFilters();
    }

    applyFilters() {
        this.filteredElements = this.elements.filter(element => {
            return Object.keys(this.activeFilters).every(filterType => {
                const config = this.filtersConfig[filterType];
                if (config && config.filter) {
                    return config.filter(element, this.activeFilters[filterType]);
                }
                return true;
            });
        });

        this.render();

        if (this.syncUrlState) {
            Object.keys(this.activeFilters).forEach((key) => {
                const value = this.activeFilters[key];
                const paramKey = `filter_${key}`;
                let paramValue = '';

                if (Array.isArray(value)) {
                    paramValue = value.join(',');
                } else if (typeof value === 'object' && value.optionValue) {
                    paramValue = value.optionValue;
                } else {
                    paramValue = value;
                }

                const url = new URL(window.location);
                url.searchParams.set(paramKey, paramValue);
                window.history.replaceState({}, '', url);
            });

            Object.keys(this.filtersConfig).forEach(filterType => {
                if (!this.activeFilters[filterType]) {
                    const paramKey = `filter_${filterType}`;
                    const url = new URL(window.location);
                    if (url.searchParams.has(paramKey)) {
                        url.searchParams.delete(paramKey);
                        window.history.replaceState({}, '', url);
                    }
                }
            });
        }

        this.emitStateChange();

    }

    add(element) {
        this.elements.push(element);
        this.applyFilters();
    }

    addAll(elements) {
        this.elements.push(...elements);
        this.applyFilters();
    }

    render() {
        this.container.innerHTML = '';

        const elementsToRender = this.filteredElements.length > 0 || Object.keys(this.activeFilters).length > 0
            ? this.filteredElements
            : this.elements;

        if (elementsToRender.length === 0 && this.elements.length > 0) {
            this._teardownVirtualScroll();
            this.renderedItems = [];
            const noResults = document.createElement('div');
            noResults.className = 'list-no-results';
            noResults.innerHTML = '<i class="ph ph-funnel-x"></i><span>No items match the current filters.</span>';
            this.container.appendChild(noResults);
            return;
        }

        const flatCount = elementsToRender.length;
        const useVirtual = this._shouldVirtualize(flatCount);

        if (useVirtual) {
            this._virtualActive = true;
            this._lastVirtualElementsSource = elementsToRender;
            this.rebuildVirtualStructure(elementsToRender);
            this._vsAnchor = document.createElement('div');
            this._vsAnchor.className = 'list-vs-anchor';
            this._vsInner = document.createElement('div');
            this._vsInner.className = 'list-vs-inner';
            this._vsAnchor.appendChild(this._vsInner);
            this.container.appendChild(this._vsAnchor);
            this._ensureVirtualBindings();
            this._runVirtualSlice(true);
            return;
        }

        this._teardownVirtualScroll();
        this.renderedItems = [];

        const groups = this.groupElements(elementsToRender);

        if (groups) {
            groups.forEach(group => {
                const groupContainer = document.createElement('div');
                groupContainer.className = 'list-group';

                const groupHeader = document.createElement('div');
                groupHeader.className = 'list-group-header';
                groupHeader.innerHTML = `
                    <span class="list-group-label">${group.label}</span>
                    <span class="list-group-count">${group.elements.length}</span>
                `;

                groupContainer.appendChild(groupHeader);

                const toggle = document.createElement('span');
                toggle.className = 'list-group-toggle';
                toggle.innerHTML = '<i class="ph ph-caret-down"></i>';
                const groupContent = document.createElement('div');
                groupContent.className = 'list-group-content';

                groupHeader.addEventListener('click', () => {
                    groupContent.classList.toggle('collapsed');
                    toggle.innerHTML = groupContent.classList.contains('collapsed')
                        ? '<i class="ph ph-caret-right"></i>'
                        : '<i class="ph ph-caret-down"></i>';
                });
                groupHeader.appendChild(toggle);

                group.elements.forEach(element => {
                    groupContent.appendChild(this.renderElement(element, true));
                });

                groupContainer.appendChild(groupContent);
                this.container.appendChild(groupContainer);
            });
        } else {
            elementsToRender.forEach(element => {
                this.container.appendChild(this.renderElement(element, true));
            });
        }
    }

    _shouldVirtualize(flatItemCount) {
        return Boolean(this._virtualScrollCfg && flatItemCount >= this._virtualScrollCfg.minItems);
    }

    _teardownVirtualScroll() {
        if (this._vsBound && this._vsOnScroll) {
            window.removeEventListener('scroll', this._vsOnScroll);
            window.removeEventListener('resize', this._vsOnScroll);
        }
        this._vsBound = false;
        this._virtualActive = false;
        this.collapsedGroupKeys.clear();
        this._vsAnchor = null;
        this._vsInner = null;
    }

    _ensureVirtualBindings() {
        if (this._vsBound) {
            return;
        }
        this._vsBound = true;
        this._vsOnScroll = () => this._scheduleVirtualRefresh();
        window.addEventListener('scroll', this._vsOnScroll, { passive: true });
        window.addEventListener('resize', this._vsOnScroll);
    }

    _scheduleVirtualRefresh() {
        if (this._vsRafQueued) {
            return;
        }
        this._vsRafQueued = true;
        requestAnimationFrame(() => {
            this._vsRafQueued = false;
            if (this._virtualActive) {
                this._runVirtualSlice(false);
            }
        });
    }

    _rowHeight(kind) {
        if (kind === 'header') {
            return this._vsMeasuredHeaderHeight || this._vsHeaderHeightDefault;
        }
        return this._vsMeasuredItemHeight || this._vsItemHeightDefault;
    }

    rebuildVirtualStructure(elementsToRender) {
        const groups = this.groupElements(elementsToRender);
        const rows = [];
        const flatElements = [];
        const itemOffsetY = [];
        let yAcc = 0;

        if (groups) {
            groups.forEach((group) => {
                const hHead = this._rowHeight('header');
                rows.push({
                    kind: 'header',
                    key: group.key,
                    label: group.label,
                    count: group.elements.length,
                    height: hHead
                });
                yAcc += hHead;

                const collapsed = this.collapsedGroupKeys.has(group.key);
                if (!collapsed) {
                    group.elements.forEach((element) => {
                        itemOffsetY.push(yAcc);
                        const ih = this._rowHeight('item');
                        rows.push({
                            kind: 'item',
                            element,
                            groupKey: group.key,
                            height: ih
                        });
                        yAcc += ih;
                        flatElements.push(element);
                    });
                }
            });
        } else {
            elementsToRender.forEach((element) => {
                itemOffsetY.push(yAcc);
                const ih = this._rowHeight('item');
                rows.push({
                    kind: 'item',
                    element,
                    height: ih
                });
                yAcc += ih;
                flatElements.push(element);
            });
        }

        this.virtualRows = rows;
        this.virtualFlatElements = flatElements;
        this.virtualItemOffsetY = itemOffsetY;

        const pref = [0];
        rows.forEach((r) => {
            pref.push(pref[pref.length - 1] + r.height);
        });
        this.virtualPrefix = pref;
        this.virtualTotalHeight = pref[pref.length - 1] || 0;
    }

    _createVirtualGroupHeaderRow(meta) {
        const collapsed = this.collapsedGroupKeys.has(meta.key);
        const groupWrap = document.createElement('div');
        groupWrap.className = 'list-group list-vs-virtual-group';

        const groupHeader = document.createElement('div');
        groupHeader.className = 'list-group-header';

        const labelSpan = document.createElement('span');
        labelSpan.className = 'list-group-label';
        labelSpan.textContent = meta.label;

        const countSpan = document.createElement('span');
        countSpan.className = 'list-group-count';
        countSpan.textContent = String(meta.count);

        groupHeader.appendChild(labelSpan);
        groupHeader.appendChild(countSpan);

        const toggle = document.createElement('span');
        toggle.className = 'list-group-toggle';
        toggle.innerHTML = collapsed
            ? '<i class="ph ph-caret-right"></i>'
            : '<i class="ph ph-caret-down"></i>';

        groupHeader.appendChild(toggle);

        groupHeader.addEventListener('click', () => {
            if (this.collapsedGroupKeys.has(meta.key)) {
                this.collapsedGroupKeys.delete(meta.key);
            } else {
                this.collapsedGroupKeys.add(meta.key);
            }
            this.rebuildVirtualStructure(this._lastVirtualElementsSource);
            this._runVirtualSlice(false);
        });

        groupWrap.appendChild(groupHeader);
        return groupWrap;
    }

    /**
     * Pass true once after structure changes so row heights match CSS; false during scroll/reflow.
     * @param {boolean} allowRemeasure
     */
    _runVirtualSlice(allowRemeasure = false) {
        const inner = this._vsInner;
        const anchor = this._vsAnchor;
        if (!inner || !anchor || !this.virtualRows.length) {
            this.renderedItems = [];
            return;
        }

        if (allowRemeasure === true) {
            inner.style.paddingTop = '0';
            inner.style.paddingBottom = '0';
            inner.replaceChildren();
            const probeRows = this.virtualRows.slice(0, Math.min(2, this.virtualRows.length));
            probeRows.forEach((row) => {
                if (row.kind === 'header') {
                    inner.appendChild(this._createVirtualGroupHeaderRow(row));
                } else {
                    inner.appendChild(this.renderElement(row.element, false));
                }
            });
            const itemEl = inner.querySelector('.list-element');
            const groupEl = inner.querySelector('.list-vs-virtual-group');
            let changed = false;
            if (itemEl) {
                const oh = List._outerHeight(itemEl);
                if (oh > 0 && (!this._vsMeasuredItemHeight || Math.abs(oh - this._vsMeasuredItemHeight) > 2)) {
                    this._vsMeasuredItemHeight = oh;
                    changed = true;
                }
            }
            if (groupEl) {
                const oh = List._outerHeight(groupEl);
                if (oh > 0 && (!this._vsMeasuredHeaderHeight || Math.abs(oh - this._vsMeasuredHeaderHeight) > 2)) {
                    this._vsMeasuredHeaderHeight = oh;
                    changed = true;
                }
            }
            if (changed && !this._vsMeasureRecursing) {
                this._vsMeasureRecursing = true;
                this.rebuildVirtualStructure(this._lastVirtualElementsSource);
                this._vsMeasureRecursing = false;
            }
        }

        const pref = this.virtualPrefix;
        const n = this.virtualRows.length;
        const viewportH = window.innerHeight;
        const avgRowH = this.virtualTotalHeight > 0 && n > 0 ? this.virtualTotalHeight / n : this._vsItemHeightDefault;
        const overscanPx = this._vsOverscan * avgRowH;

        const anchorTopDoc = anchor.getBoundingClientRect().top + window.scrollY;
        const scrollTop = Math.max(0, window.scrollY - anchorTopDoc);
        const maxTop = Math.max(0, pref[n] - viewportH);
        const scrollTopClamped = Math.min(scrollTop, maxTop);

        let startRow = 0;
        let hi = n;
        const topTarget = scrollTopClamped - overscanPx;
        while (startRow < hi) {
            const mid = (startRow + hi) >> 1;
            if (pref[mid + 1] <= topTarget) {
                startRow = mid + 1;
            } else {
                hi = mid;
            }
        }

        let endRow = startRow;
        let hi2 = n;
        const bottomTarget = scrollTopClamped + viewportH + overscanPx;
        while (endRow < hi2) {
            const mid = (endRow + hi2 + 1) >> 1;
            if (pref[mid] < bottomTarget) {
                endRow = mid;
            } else {
                hi2 = mid - 1;
            }
        }
        endRow = Math.min(n - 1, Math.max(startRow, endRow));

        const paddingTop = pref[startRow];
        const paddingBottom = pref[n] - pref[endRow + 1];

        inner.style.paddingTop = `${paddingTop}px`;
        inner.style.paddingBottom = `${paddingBottom}px`;

        const visibleMap = new Map();
        const frag = document.createDocumentFragment();
        for (let i = startRow; i <= endRow; i += 1) {
            const row = this.virtualRows[i];
            if (row.kind === 'header') {
                frag.appendChild(this._createVirtualGroupHeaderRow(row));
            } else {
                const node = this.renderElement(row.element, false);
                visibleMap.set(row.element.id, node);
                frag.appendChild(node);
            }
        }
        inner.replaceChildren(frag);

        this.renderedItems = this.virtualFlatElements.map((el) => ({
            element: el,
            domNode: visibleMap.get(el.id) || null
        }));

        if (this.selectedIndex >= 0 && this.renderedItems[this.selectedIndex]?.domNode) {
            this.renderedItems[this.selectedIndex].domNode.classList.add('selected');
        }
    }

    static _outerHeight(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const mb = parseFloat(style.marginBottom) || 0;
        const mt = parseFloat(style.marginTop) || 0;
        return rect.height + mb + mt;
    }

    renderElement(element, collectToRendered = true) {
        const inner = this.renderer(element);

        const elDiv = document.createElement('div');
        elDiv.className = 'list-element';

        if (typeof inner === 'string') {
            elDiv.innerHTML = inner;
        } else {
            elDiv.appendChild(inner);
        }

        elDiv.addEventListener('click', () => {
            if (element.onClick) {
                element.onClick(element);
            }
        });

        if (this.onDelete) {
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'list-element-delete-btn';
            deleteBtn.innerHTML = '<i class="ph ph-trash"></i>';
            deleteBtn.title = 'Delete';
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (confirm('Are you sure you want to delete this item?')) {
                    this.onDelete(element);
                }
            });
            elDiv.appendChild(deleteBtn);
        }

        if (collectToRendered) {
            this.renderedItems.push({ element, domNode: elDiv });
        }

        return elDiv;
    }

    remove(itemId) {
        const index = this.elements.findIndex(el => el.id === itemId);
        if (index > -1) {
            this.elements.splice(index, 1);
        }

        this.applyFilters();
    }
}

List._normalizeVirtualScrollOption = function (vs) {
    if (!vs) {
        return null;
    }
    if (vs === true) {
        return { minItems: 48, overscan: 8 };
    }
    return {
        minItems: Number.isFinite(vs.minItems) ? vs.minItems : 48,
        overscan: Number.isFinite(vs.overscan) ? vs.overscan : 8
    };
};

