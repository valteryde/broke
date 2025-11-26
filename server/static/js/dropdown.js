/*
 * Reusable Dropdown Menu with Submenu Support
 * 
 * Usage:
 * const dropdown = new Dropdown(triggerElement, {
 *     items: [
 *         { 
 *             label: 'Item 1', 
 *             icon: 'ph-tag',
 *             submenu: [
 *                 { label: 'Sub item 1', value: 'sub1', icon: 'ph-check' },
 *                 { label: 'Sub item 2', value: 'sub2' }
 *             ],
 *             onSubmenuClick: (item, value) => console.log(value)
 *         },
 *         { label: 'Item 2', icon: 'ph-user', onClick: () => console.log('clicked') },
 *         { divider: true },
 *         { label: 'Item 3', disabled: true }
 *     ],
 *     onOpen: () => console.log('opened'),
 *     onClose: () => console.log('closed'),
 *     closeOnClick: true,
 *     closeOnOutsideClick: true,
 *     position: 'bottom-left' // 'bottom-left', 'bottom-right'
 * });
 * 
 * // Methods
 * dropdown.open();
 * dropdown.close();
 * dropdown.toggle();
 * dropdown.updateItems(newItems);
 * dropdown.destroy();
 */

class Dropdown {
    constructor(trigger, options = {}) {
        this.trigger = typeof trigger === 'string' ? document.querySelector(trigger) : trigger;
        this.options = {
            items: [],
            onOpen: null,
            onClose: null,
            closeOnClick: true,
            closeOnOutsideClick: true,
            position: 'bottom-left',
            ...options
        };
        
        this.isOpen = false;
        this.menu = null;
        
        this.init();
    }
    
    init() {
        // Wrap trigger if not already wrapped
        if (!this.trigger.parentElement.classList.contains('dropdown-wrapper')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'dropdown-wrapper';
            this.trigger.parentNode.insertBefore(wrapper, this.trigger);
            wrapper.appendChild(this.trigger);
        }
        
        this.wrapper = this.trigger.parentElement;
        this.trigger.classList.add('dropdown-trigger');
        
        // Create menu
        this.menu = document.createElement('div');
        this.menu.className = 'dropdown-menu';
        if (this.options.position === 'bottom-right') {
            this.menu.classList.add('dropdown-right');
        }
        
        this.renderItems();
        this.wrapper.appendChild(this.menu);
        
        // Event listeners
        this.trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });
        
        if (this.options.closeOnOutsideClick) {
            document.addEventListener('click', (e) => {
                if (!this.wrapper.contains(e.target)) {
                    this.close();
                }
            });
        }
        
        // Prevent menu clicks from closing (unless closeOnClick is true and it's a final action)
        this.menu.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }
    
    renderItems() {
        this.menu.innerHTML = '';
        
        this.options.items.forEach((item, index) => {
            if (item.divider) {
                const divider = document.createElement('div');
                divider.className = 'dropdown-divider';
                this.menu.appendChild(divider);
                return;
            }
            
            const itemEl = document.createElement('div');
            itemEl.className = 'dropdown-item';
            if (item.disabled) itemEl.classList.add('disabled');
            
            const hasSubmenu = item.submenu || item.getSubmenuItems;
            
            let content = '';
            if (item.icon) content += `<i class="ph ${item.icon}"></i> `;
            content += `<span>${item.label}</span>`;
            if (hasSubmenu) content += `<i class="ph ph-caret-right dropdown-submenu-arrow"></i>`;
            
            itemEl.innerHTML = content;
            
            // Handle submenu (static or dynamic)
            if (hasSubmenu) {
                itemEl.classList.add('has-submenu');
                const submenu = this.createSubmenu(item.submenu || [], item.onSubmenuClick, !!item.getSubmenuItems);
                itemEl.appendChild(submenu);
                
                // Populate submenu on hover if dynamic
                if (item.getSubmenuItems) {
                    itemEl.addEventListener('mouseenter', () => {
                        const dynamicItems = item.getSubmenuItems();
                        this.populateSubmenu(submenu, dynamicItems, item.onSubmenuClick);
                    });
                }
            } else if (item.onClick && !item.disabled) {
                itemEl.addEventListener('click', () => {
                    item.onClick(item);
                    if (this.options.closeOnClick) {
                        this.close();
                    }
                });
            }
            
            this.menu.appendChild(itemEl);
        });
    }
    
    createSubmenu(items, onSubmenuClick, isDynamic = false) {
        const submenu = document.createElement('div');
        submenu.className = 'dropdown-submenu';
        
        if (this.options.position === 'bottom-right') {
            submenu.classList.add('dropdown-submenu-left');
        }
        
        if (!isDynamic) {
            this.populateSubmenu(submenu, items, onSubmenuClick);
        }
        
        return submenu;
    }
    
    populateSubmenu(submenu, items, onSubmenuClick) {
        submenu.innerHTML = '';
        
        if (!items || items.length === 0) {
            const emptyItem = document.createElement('div');
            emptyItem.className = 'dropdown-submenu-item disabled';
            emptyItem.textContent = 'No options available';
            submenu.appendChild(emptyItem);
            return;
        }
        
        items.forEach(subItem => {
            const subItemEl = document.createElement('div');
            subItemEl.className = 'dropdown-submenu-item';
            if (subItem.disabled) subItemEl.classList.add('disabled');
            if (subItem.selected) subItemEl.classList.add('selected');
            if (subItem.colorClass) subItemEl.classList.add(subItem.colorClass);
            
            let content = '';
            if (subItem.selected) content += `<i class="ph ph-check"></i> `;
            if (subItem.icon) content += `<i class="ph ${subItem.icon}"></i> `;
            content += subItem.label;
            
            subItemEl.innerHTML = content;
            
            if (!subItem.disabled) {
                subItemEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (onSubmenuClick) {
                        onSubmenuClick(subItem, subItem.value);
                    }
                    if (this.options.closeOnClick) {
                        this.close();
                    }
                });
            }
            
            submenu.appendChild(subItemEl);
        });
    }
    
    updateItems(items) {
        this.options.items = items;
        this.renderItems();
    }
    
    open() {
        if (this.isOpen) return;
        this.isOpen = true;
        this.menu.classList.add('show');
        if (this.options.onOpen) {
            this.options.onOpen();
        }
    }
    
    close() {
        if (!this.isOpen) return;
        this.isOpen = false;
        this.menu.classList.remove('show');
        if (this.options.onClose) {
            this.options.onClose();
        }
    }
    
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }
    
    destroy() {
        this.menu.remove();
        this.trigger.classList.remove('dropdown-trigger');
        // Unwrap if we created the wrapper
        if (this.wrapper.classList.contains('dropdown-wrapper') && this.wrapper.children.length === 1) {
            this.wrapper.parentNode.insertBefore(this.trigger, this.wrapper);
            this.wrapper.remove();
        }
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Dropdown;
}
