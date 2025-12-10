/*
 * Shortcut Manager
 * Handles keyboard shortcuts application-wide
 */

class ShortcutManager {
    constructor() {
        this.shortcuts = {};
        this.init();
        this.locked = false;
    }

    init() {
        document.addEventListener('keydown', (e) => this.handleKeyDown(e));
    }

    /**
     * Register a shortcut
     * @param {string} key - The key to listen for (e.g., 'j', 'k', 'Enter')
     * @param {function} callback - Function to execute
     * @param {string} description - Description for the cheat sheet
     * @param {boolean} allowInInput - Whether to allow triggering in input fields (default false)
     * @param {function} target - Optional function that returns the target element for the shortcut
     */
    register(key, callback, description = '', allowInInput = false, target = null) {
        this.shortcuts[key.toLowerCase()] = { callback, description, allowInInput, target };
    }

    /**
     * Unregister a shortcut
     * @param {string} key 
     */
    unregister(key) {
        delete this.shortcuts[key.toLowerCase()];
    }

    /**
     * Lock the shortcut manager
     * @param {boolean} locked 
     */
    lock(locked) {
        this.locked = locked;
    }

    /**
     * Unlock the shortcut manager
     */
    unlock() {
        this.locked = false;
    }

    handleKeyDown(e) {

        const key = e.key.toLowerCase();

        if (this.shortcuts[key]) {
            const cleanKey = key;
            const shortcut = this.shortcuts[cleanKey];

            // If a custom target is provided, find it first
            let target = e.target;
            if (shortcut.target) {
                target = shortcut.target();
            }
            if (!target) {
                return;
            }

            // If we are in an input and this shortcut is not allowed in inputs, skip
            if (this.locked) {
                return;
            }

            e.preventDefault();
            try {
                shortcut.callback(target, e);
            } catch (error) {
                console.error('Shortcut execution failed:', error);
            }
        }
    }
}

// Global instance
window.shortcuts = new ShortcutManager();
