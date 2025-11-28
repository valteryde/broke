
/*
 * List class with modular filtering and grouping support
 * 
 * Usage:
 * const list = new List('container-id', {
 *     filters: {
 *         search: { placeholder: 'Search...' },
 *         labels: { label: 'Labels' },
 *         assignees: { label: 'Assignees' },
 *         urgency: { label: 'Urgency' },
 *         dateRange: { label: 'Date Range' }
 *     },
 *     groupBy: {
 *         options: ['urgency', 'assignees', 'labels', 'none'],
 *         default: 'none'
 *     }
 * });
 */

// Filter type definitions with icons and display names
// TODO: Move filter functions to separate modules for better maintainability
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

// Group type definitions
// TODO: Move group functions to separate modules for better maintainability
const GroupTypes = {
    none: {
        label: 'None',
        icon: 'ph-list',
        getGroupKey: () => null,
        getGroupLabel: () => null
    },
    urgency: {
        label: 'Urgency',
        icon: 'ph-warning',
        getGroupKey: (element) => element.urgency || 'none',
        getGroupLabel: (key) => {
            const labels = { urgent: 'Urgent', high: 'High', medium: 'Medium', low: 'Low', none: 'No urgency' };
            return labels[key] || key;
        },
        order: ['urgent', 'high', 'medium', 'low', 'none']
    },
    assignees: {
        label: 'Assignee',
        icon: 'ph-users',
        getGroupKey: (element) => element.assignees && element.assignees.length > 0 ? element.assignees[0] : 'unassigned',
        getGroupLabel: (key) => key === 'unassigned' ? 'Unassigned' : key
    },
    labels: {
        label: 'Label',
        icon: 'ph-tag',
        getGroupKey: (element) => element.labels && element.labels.length > 0 ? element.labels[0].text : 'unlabeled',
        getGroupLabel: (key) => key === 'unlabeled' ? 'No labels' : key
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
        this.currentGroupBy = options.groupBy?.default || 'none';
        
        // Create wrapper structure
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'list-wrapper';
        this.container.parentNode.insertBefore(this.wrapper, this.container);
        
        // Create filter bar if filters or groupBy are configured
        if (options.filters || options.groupBy) {
            this.filterBar = this.createFilterBar(options.filters || {});
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
        
        // Top row: search and add filter button
        const filterOptionsRow = document.createElement('div');
        filterOptionsRow.className = 'list-filter-options';
        
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
            filterOptionsRow.appendChild(searchWrapper);
        }
        
        // Add filter dropdown using reusable Dropdown class
        const addFilterWrapper = document.createElement('div');
        addFilterWrapper.className = 'list-add-filter-wrapper';
        
        const addFilterBtn = document.createElement('button');
        addFilterBtn.className = 'list-add-filter-btn';
        addFilterBtn.innerHTML = '<i class="ph ph-funnel"></i> <span>Add filter</span> <i class="ph ph-caret-down"></i>';
        
        addFilterWrapper.appendChild(addFilterBtn);
        filterOptionsRow.appendChild(addFilterWrapper);
        
        // Group by dropdown
        if (this.options.groupBy) {
            const groupByWrapper = document.createElement('div');
            groupByWrapper.className = 'list-group-by-wrapper';
            
            const groupByBtn = document.createElement('button');
            groupByBtn.className = 'list-group-by-btn';
            this.groupByBtn = groupByBtn;
            this.updateGroupByButtonLabel();
            
            groupByWrapper.appendChild(groupByBtn);
            filterOptionsRow.appendChild(groupByWrapper);
            
            // Build group by dropdown items
            const groupByItems = (this.options.groupBy.options || ['none', 'urgency', 'assignees', 'labels']).map(groupType => ({
                label: GroupTypes[groupType]?.label || groupType,
                icon: GroupTypes[groupType]?.icon || 'ph-list',
                onClick: () => {
                    this.setGroupBy(groupType);
                }
            }));
            
            this.groupByDropdown = new Dropdown(groupByBtn, {
                items: groupByItems,
                closeOnClick: true
            });
        }

        const createButton = document.createElement('button');
        createButton.className = 'list-create-btn';
        createButton.innerHTML = '<span> <i class="ph ph-plus"></i> Add </span>';
        filterOptionsRow.appendChild(createButton);
        
        // Bottom row: Active filters container (chips)
        this.activeFiltersContainer = document.createElement('div');
        this.activeFiltersContainer.className = 'list-active-filters';
        
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
        
        filterBar.appendChild(filterOptionsRow);
        filterBar.appendChild(this.activeFiltersContainer);
        
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
    
    // Grouping methods
    updateGroupByButtonLabel() {
        if (this.groupByBtn) {
            const groupType = GroupTypes[this.currentGroupBy];
            const label = groupType?.label || 'Group';
            this.groupByBtn.innerHTML = `<i class="ph ${groupType?.icon || 'ph-list'}"></i> <span>Group: ${label}</span> <i class="ph ph-caret-down"></i>`;
        }
    }
    
    setGroupBy(groupType) {
        this.currentGroupBy = groupType;
        this.updateGroupByButtonLabel();
        this.render();
    }
    
    groupElements(elements) {
        if (this.currentGroupBy === 'none' || !GroupTypes[this.currentGroupBy]) {
            return null;
        }
        
        const groupType = GroupTypes[this.currentGroupBy];
        const groups = new Map();
        
        elements.forEach(element => {
            const key = groupType.getGroupKey(element);
            if (!groups.has(key)) {
                groups.set(key, []);
            }
            groups.get(key).push(element);
        });
        
        // Sort groups if order is defined
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
        
        // Check if we should group the elements
        const groups = this.groupElements(elementsToRender);
        
        if (groups) {
            // Render grouped elements
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
                
                const groupContent = document.createElement('div');
                groupContent.className = 'list-group-content';
                
                group.elements.forEach(element => {
                    groupContent.appendChild(this.renderElement(element));
                });
                
                groupContainer.appendChild(groupContent);
                this.container.appendChild(groupContainer);
            });
        } else {
            // Render flat list
            elementsToRender.forEach(element => {
                this.container.appendChild(this.renderElement(element));
            });
        }
    }
    
    renderElement(element) {
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
                ${(element.labels || []).map(label => `<span class="list-label"> <span class="list-label-circle" style="background-color: ${label.color}"></span> ${label.text}  </span>`).join('')}
            </span>
            <span class="list-assignees">
                ${(element.assignees || []).map(assignee => `<span class="list-assignee"> <i class="ph ph-user"></i>  ${assignee}</span>`).join('')}
            </span>
            <span class="list-date">
                ${dateString}
            </span>
        `;
        
        const elDiv = document.createElement('div');
        elDiv.className = 'list-element';
        elDiv.appendChild(inner);

        elDiv.addEventListener('click', () => {
            if (element.onClick) {
                element.onClick(element);
            }
        });

        return elDiv;
    }
}

