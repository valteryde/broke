/**
 * Modal Component
 * Reusable modal dialog system
 * 
 * Usage:
 * Modal.show('Title', '<form>...</form>', { onClose: () => {} });
 * Modal.close();
 * 
 * Or use the class-based approach for more control:
 * const modal = new Modal({
 *     title: 'My Modal',
 *     content: '<p>Content here</p>',
 *     onClose: () => {}
 * });
 * modal.show();
 * modal.close();
 */

class Modal {
    constructor(options = {}) {
        this.title = options.title || '';
        this.content = options.content || '';
        this.onClose = options.onClose || (() => { });
        this.onOpen = options.onOpen || (() => { });
        this.closeOnOverlay = options.closeOnOverlay;

        if (this.closeOnOverlay === undefined) {
            this.closeOnOverlay = true;
        }

        this.closeOnEscape = options.closeOnEscape;

        if (this.closeOnEscape === undefined) {
            this.closeOnEscape = true;
        }

        this.element = null;
        this.escapeHandler = null;
    }

    show() {
        // Remove any existing modal
        Modal.close();

        this.element = document.createElement('div');
        this.element.className = 'modal-overlay';
        this.element.innerHTML = `
            <div class="modal">
                <div class="modal-header">
                    <h2>${this.escapeHtml(this.title)}</h2>
                    <button class="btn-icon modal-close-btn">
                        <i class="ph ph-x"></i>
                    </button>
                </div>
                <div class="modal-content">
                    ${this.content}
                </div>
            </div>
        `;

        document.body.appendChild(this.element);

        // Close button handler
        const closeBtn = this.element.querySelector('.modal-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        // Overlay click handler
        if (this.closeOnOverlay) {
            this.element.addEventListener('click', (e) => {
                if (e.target === this.element) {
                    this.close();
                }
            });
        }

        // Escape key handler
        if (this.closeOnEscape) {
            this.escapeHandler = (e) => {
                if (e.key === 'Escape') {
                    this.close();
                }
            };
            document.addEventListener('keydown', this.escapeHandler);
        }

        // Call onOpen callback
        this.onOpen(this.element);

        return this;
    }

    close() {
        if (this.element) {
            this.element.remove();
            this.element = null;
        }

        if (this.escapeHandler) {
            document.removeEventListener('keydown', this.escapeHandler);
            this.escapeHandler = null;
        }

        this.onClose();
    }

    getElement() {
        return this.element;
    }

    getContentElement() {
        return this.element?.querySelector('.modal-content');
    }

    setContent(content) {
        const contentEl = this.getContentElement();
        if (contentEl) {
            contentEl.innerHTML = content;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Static methods for simple usage
    static show(title, content, options = {}) {
        const modal = new Modal({
            title,
            content,
            ...options
        });
        modal.show();
        return modal;
    }

    static close() {
        const existingOverlay = document.querySelector('.modal-overlay');
        if (existingOverlay) {
            existingOverlay.remove();
        }
    }
}

// Keep backward compatibility with window functions
window.showModal = (title, content, options = {}) => Modal.show(title, content, options);
window.closeModal = () => Modal.close();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Modal;
}
