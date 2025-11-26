
/*
 * List class with modular filtering support
 * 
 * Usage:
 * const list = new List('container-id', {
 *     filters: {
 *         search: { placeholder: 'Search...' },
 *         labels: { label: 'Labels' },
 *         assignees: { label: 'Assignees' },
 *         urgency: { label: 'Urgency' },
 *         dateRange: { label: 'Date Range' }
 *     }
 * });
 */

// Filter type definitions with icons and display names
const FilterTypes = {
    search: { 
        icon: 'ph-magnifying-glass', 
        label: 'Search',
        filter: (element, value) => {
            if (!value) return true;
            const searchText = `${element.id} ${element.title} ${element.description}`.toLowerCase();
            return searchText.includes(value.toLowerCase());
        }
    },
    labels: { 
        icon: 'ph-tag', 
        label: 'Labels',
        filter: (element, values) => {
            if (!values || values.length === 0) return true;
            const elementLabels = element.labels.map(l => l.text);
            return values.every(v => elementLabels.includes(v));
        }
    },
    assignees: { 
        icon: 'ph-users', 
        label: 'Assignees',
        filter: (element, values) => {
            if (!values || values.length === 0) return true;
            return values.every(v => element.assignees.includes(v));
        }
    },
    urgency: { 
        icon: 'ph-warning', 
        label: 'Urgency',
        filter: (element, values) => {
            if (!values || values.length === 0) return true;
            return values.includes(element.urgency);
        }
    },
    dateRange: { 
        icon: 'ph-calendar', 
        label: 'Date Range',
        filter: (element, value) => {
            if (!value || (!value.from && !value.to)) return true;
            const elementDate = element.createdAt ? new Date(element.createdAt) : null;
            if (!elementDate) return false;
            if (value.from && elementDate < value.from) return false;
            if (value.to && elementDate > value.to) return false;
            return true;
        }
    }
};

class List {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.container.classList.add('list-container');
        this.elements = [];
        this.filteredElements = [];
        this.options = options;
        this.activeFilters = {};
        this.activeFilterChips = {};
        
        // Create wrapper structure
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'list-wrapper';
        this.container.parentNode.insertBefore(this.wrapper, this.container);
        
        // Create filter bar if filters are configured
        if (options.filters) {
            this.filterBar = this.createFilterBar(options.filters);
            this.wrapper.appendChild(this.filterBar);
        }
        
        this.wrapper.appendChild(this.container);
    }
    
    // Get submenu options for each filter type
    getFilterOptions(filterType) {
        switch (filterType) {
            case 'labels':
                return this.extractLabels().map(l => ({ value: l.text, label: l.text, icon: 'ph-fill ph-circle', colorClass: `filter-color-${l.color}` }));
            case 'assignees':
                return this.extractAssignees().map(a => ({ value: a, label: a }));
            case 'urgency':
                return [
                    { value: 'urgent', label: 'Urgent', icon: 'ph-warning'},
                    { value: 'high', label: 'High', icon: 'ph-cell-signal-high'},
                    { value: 'medium', label: 'Medium', icon: 'ph-cell-signal-medium'},
                    { value: 'low', label: 'Low', icon: 'ph-cell-signal-low'}
                ];
            case 'dateRange':
                return [
                    { value: 'last7', label: 'Last 7 days', icon: 'ph-clock-counter-clockwise' },
                    { value: 'last14', label: 'Last 14 days', icon: 'ph-clock-counter-clockwise' },
                    { value: 'last30', label: 'Last 30 days', icon: 'ph-clock-counter-clockwise' },
                    { value: 'older7', label: 'Older than 7 days', icon: 'ph-clock-clockwise' },
                    { value: 'older14', label: 'Older than 14 days', icon: 'ph-clock-clockwise' },
                    { value: 'older30', label: 'Older than 30 days', icon: 'ph-clock-clockwise' }
                ];
            default:
                return [];
        }
    }
    
    // Convert date range option to actual date filter
    getDateRangeFromOption(optionValue) {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        
        switch (optionValue) {
            case 'last7':
                const last7 = new Date(today);
                last7.setDate(last7.getDate() - 7);
                return { from: last7, to: null };
            case 'last14':
                const last14 = new Date(today);
                last14.setDate(last14.getDate() - 14);
                return { from: last14, to: null };
            case 'last30':
                const last30 = new Date(today);
                last30.setDate(last30.getDate() - 30);
                return { from: last30, to: null };
            case 'older7':
                const older7 = new Date(today);
                older7.setDate(older7.getDate() - 7);
                return { from: null, to: older7 };
            case 'older14':
                const older14 = new Date(today);
                older14.setDate(older14.getDate() - 14);
                return { from: null, to: older14 };
            case 'older30':
                const older30 = new Date(today);
                older30.setDate(older30.getDate() - 30);
                return { from: null, to: older30 };
            default:
                return { from: null, to: null };
        }
    }
    
    createFilterBar(filtersConfig) {
        const filterBar = document.createElement('div');
        filterBar.className = 'list-filter-bar';
        
        // Always-visible search bar (if configured)
        if (filtersConfig.search) {
            const searchWrapper = document.createElement('div');
            searchWrapper.className = 'list-search-wrapper';
            
            const searchIcon = document.createElement('i');
            searchIcon.className = 'ph ph-magnifying-glass';
            
            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.className = 'list-search-input';
            searchInput.placeholder = filtersConfig.search.placeholder || 'Search...';
            
            searchInput.addEventListener('input', () => {
                this.activeFilters.search = searchInput.value;
                this.applyFilters();
            });
            
            searchWrapper.appendChild(searchIcon);
            searchWrapper.appendChild(searchInput);
            filterBar.appendChild(searchWrapper);
        }
        
        // Active filters container (chips)
        this.activeFiltersContainer = document.createElement('div');
        this.activeFiltersContainer.className = 'list-active-filters';
        
        // Add filter dropdown using reusable Dropdown class
        const addFilterWrapper = document.createElement('div');
        addFilterWrapper.className = 'list-add-filter-wrapper';
        
        const addFilterBtn = document.createElement('button');
        addFilterBtn.className = 'list-add-filter-btn';
        addFilterBtn.innerHTML = '<i class="ph ph-funnel"></i> <span>Add filter</span> <i class="ph ph-caret-down"></i>';
        
        addFilterWrapper.appendChild(addFilterBtn);
        
        // Build dropdown items with submenus for each filter type
        const dropdownItems = [];
        Object.keys(filtersConfig).forEach(filterType => {
            if (FilterTypes[filterType] && filterType !== 'search') {
                dropdownItems.push({
                    label: filtersConfig[filterType].label || FilterTypes[filterType].label,
                    icon: FilterTypes[filterType].icon,
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
        
        filterBar.appendChild(this.activeFiltersContainer);
        filterBar.appendChild(addFilterWrapper);
        
        return filterBar;
    }
    
    isOptionSelected(filterType, value) {
        const filter = this.activeFilters[filterType];
        if (!filter) return false;
        
        if (filterType === 'dateRange') {
            return filter.optionValue === value;
        }
        
        if (Array.isArray(filter)) {
            return filter.includes(value);
        }
        
        return filter === value;
    }
    
    toggleFilterOption(filterType, option) {
        if (filterType === 'dateRange') {
            // Date range is single-select
            if (this.activeFilters.dateRange?.optionValue === option.value) {
                this.removeFilter(filterType);
            } else {
                const dateRange = this.getDateRangeFromOption(option.value);
                dateRange.optionValue = option.value;
                dateRange.optionLabel = option.label;
                this.activeFilters.dateRange = dateRange;
                this.updateFilterChip(filterType, option.label);
            }
        } else {
            // Multi-select filters (labels, assignees, urgency)
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
        // Remove existing chip if any
        if (this.activeFilterChips[filterType]) {
            this.activeFilterChips[filterType].remove();
        }
        
        const chip = document.createElement('div');
        chip.className = 'list-filter-chip';
        chip.dataset.filterType = filterType;
        
        const icon = document.createElement('i');
        icon.className = `ph ${FilterTypes[filterType].icon}`;
        
        const label = document.createElement('span');
        label.className = 'list-filter-chip-label';
        label.textContent = this.options.filters[filterType]?.label || FilterTypes[filterType].label;
        
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
    
    clearAllFilters() {
        this.activeFilters = {};
        
        // Remove all chips
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
                if (FilterTypes[filterType]) {
                    return FilterTypes[filterType].filter(element, this.activeFilters[filterType]);
                }
                return true;
            });
        });
        
        this.render();
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
            const noResults = document.createElement('div');
            noResults.className = 'list-no-results';
            noResults.innerHTML = '<i class="ph ph-funnel-x"></i><span>No items match the current filters.</span>';
            this.container.appendChild(noResults);
            return;
        }

        elementsToRender.forEach(element => {
            const inner = document.createElement('div');
            inner.className = 'list-element-inner';
        
            if (element.createdAt) {
                var date = new Date(element.createdAt);
                var dateString = date.toLocaleDateString();
            } else {
                var dateString = '';
            }

            inner.innerHTML = `
                <i class="ph ${element.icon} list-element-icon"></i>
                <span class="list-element-id">${element.id}</span>
                <span class="list-element-text">
                    <h3>${element.title}</h3>
                    <p style="position:absolute;top:2rem;">${element.description}</p>
                </span>
                <span class="list-labels">
                    ${element.labels.map(label => `<span class="list-label"> <span class="list-label-circle" style="background-color: ${label.color}"></span> ${label.text}  </span>`).join('')}
                </span>
                <span class="list-assignees">
                    ${element.assignees.map(assignee => `<span class="list-assignee"> <i class="ph ph-user"></i>  ${assignee}</span>`).join('')}
                </span>
                <span class="list-date">
                    ${dateString}
                </span>
            `;
            
            const elDiv = document.createElement('div');
            elDiv.className = 'list-element';
            elDiv.appendChild(inner);

            this.container.appendChild(elDiv);
        });
    }
}

