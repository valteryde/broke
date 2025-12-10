/**
 * ListModal Component
 * A command-palette style modal for selecting items from a list with search
 * 
 * Usage:
 * const modal = new ListModal({
 *     title: 'Select Status',
 *     items: [
 *         { label: 'Todo', value: 'todo', icon: 'ph-circle', colorClass: 'status-todo' },
 *         { label: 'Done', value: 'done', icon: 'ph-check-circle' }
 *     ],
 *     onSelect: (item) => { console.log(item.value); }
 * });
 * modal.show();
 */

class ListModal {
    constructor(options = {}) {
        this.title = options.title || 'Select';
        this.items = options.items || [];
        this.onSelect = options.onSelect || (() => { });
        this.placeholder = options.placeholder || 'Search...';
        this.closeOnOverlay = options.closeOnOverlay === undefined ? true : options.closeOnOverlay;
        this.closeOnEscape = options.closeOnEscape === undefined ? true : options.closeOnEscape;
        this.closeOnSelect = options.closeOnSelect === undefined ? true : options.closeOnSelect;

        this.modal = null;
        this.selectedIndex = 0;
        this.filteredItems = [];

        // Element references
        this.inputEl = null;
        this.listEl = null;
    }

    show() {
        // Create inner content
        const content = `
            <div class="list-modal-list">
                <!-- Items populated here -->
            </div>
        `;

        // Use existing Modal class
        if (typeof Modal === 'undefined') {
            console.error('ListModal: Modal class is not defined. Ensure modal.js is included.');
            return;
        }

        this.modal = new Modal({
            title: this.title,
            content: content,
            closeOnOverlay: this.closeOnOverlay,
            closeOnEscape: this.closeOnEscape,
            onOpen: (element) => {
                this.inputEl = element.querySelector('.list-modal-input');
                this.listEl = element.querySelector('.list-modal-list');

                this.filteredItems = [...this.items];
                this.renderList();

            },
            onClose: () => {
                // Cleanup if needed
                this.inputEl = null;
                this.listEl = null;
            }
        });

        this.modal.show();
    }

    moveSelection(direction) {
        if (this.filteredItems.length === 0) return;

        this.selectedIndex += direction;
        if (this.selectedIndex < 0) this.selectedIndex = 0;
        if (this.selectedIndex >= this.filteredItems.length) this.selectedIndex = this.filteredItems.length - 1;

        this.updateSelection();
    }

    updateSelection() {
        const items = this.listEl.querySelectorAll('.list-modal-item');
        items.forEach((item, index) => {
            if (index === this.selectedIndex) {
                item.classList.add('selected');
                item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                item.classList.remove('selected');
            }
        });
    }

    selectCurrent() {
        if (this.selectedIndex >= 0 && this.selectedIndex < this.filteredItems.length) {
            const item = this.filteredItems[this.selectedIndex];
            this.onSelect(item);

            // Toggle selection
            this.filteredItems[this.selectedIndex].selected = !this.filteredItems[this.selectedIndex].selected;

            if (this.closeOnSelect) {
                this.modal.close();
            } else {
                this.renderList();
            }
        }
    }

    renderList() {
        if (this.filteredItems.length === 0) {
            this.listEl.innerHTML = '<div class="list-modal-empty">No matching items</div>';
            return;
        }

        this.listEl.innerHTML = this.filteredItems.map((item, index) => {
            const isSelected = index === this.selectedIndex;
            let iconHtml = '';

            if (item.avatar) {
                iconHtml = `<span class="list-modal-avatar">${item.avatar}</span>`;
            } else if (item.icon) {
                const colorStyle = item.iconColor ? `style="color: ${item.iconColor}"` : '';
                iconHtml = `<i class="ph ${item.icon}" ${colorStyle}></i>`;
            } else if (item.color) { // For labels
                iconHtml = `<span class="list-modal-color-dot" style="background-color: ${item.color}"></span>`;
            }

            const selectedClass = isSelected ? 'selected' : '';
            const colorClass = item.colorClass || '';
            const checkMark = item.selected ? '<i class="ph ph-check list-modal-check"></i>' : '';

            return `
                <div class="list-modal-item ${selectedClass} ${colorClass}" data-index="${index}">
                    <div class="list-modal-item-icon">
                        ${iconHtml}
                    </div>
                    <div class="list-modal-item-content">
                        <div class="list-modal-item-label">${this.escapeHtml(item.label)}</div>
                        <!-- <div class="list-modal-item-sublabel">Sublabel</div> -->
                    </div>
                    <div class="list-modal-item-action">
                        ${checkMark}
                    </div>
                </div>
            `;
        }).join('');

        // Click handlers
        this.listEl.querySelectorAll('.list-modal-item').forEach(el => {
            el.addEventListener('click', () => {
                this.selectedIndex = parseInt(el.dataset.index);
                this.selectCurrent();
            });
            el.addEventListener('mouseenter', () => {
                this.selectedIndex = parseInt(el.dataset.index);
                this.updateSelection();
            });
        });

        // Re-run jdenticon if avatars are present
        if (window.jdenticon) {
            window.jdenticon();
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
