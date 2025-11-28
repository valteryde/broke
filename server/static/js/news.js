/**
 * News Page JavaScript
 * Handles interactive elements on the news/home page
 */

document.addEventListener('DOMContentLoaded', () => {
    // Initialize any interactive elements
    initActivityFeed();
    initStatCounters();
});

/**
 * Initialize the activity feed with auto-refresh capability
 */
function initActivityFeed() {
    const activityFeed = document.querySelector('.activity-feed');
    if (!activityFeed) return;

    // Add smooth scroll behavior
    activityFeed.style.scrollBehavior = 'smooth';

    // Optional: Add click handlers to activity items
    const activityItems = activityFeed.querySelectorAll('.activity-item');
    activityItems.forEach(item => {
        item.style.cursor = 'pointer';
        item.addEventListener('mouseenter', () => {
            item.style.backgroundColor = 'var(--bg-light-gray)';
        });
        item.addEventListener('mouseleave', () => {
            item.style.backgroundColor = 'transparent';
        });
    });
}

/**
 * Animate stat counters on page load
 */
function initStatCounters() {
    const statNumbers = document.querySelectorAll('.stat-number');
    
    statNumbers.forEach(stat => {
        const finalValue = parseInt(stat.textContent, 10);
        if (isNaN(finalValue)) return;
        
        // Animate from 0 to the final value
        let currentValue = 0;
        const duration = 800; // ms
        const increment = finalValue / (duration / 16); // ~60fps
        
        stat.textContent = '0';
        
        const animate = () => {
            currentValue += increment;
            if (currentValue >= finalValue) {
                stat.textContent = finalValue;
            } else {
                stat.textContent = Math.floor(currentValue);
                requestAnimationFrame(animate);
            }
        };
        
        // Start animation after a small delay for each stat
        setTimeout(() => requestAnimationFrame(animate), 100);
    });
}

/**
 * Format a timestamp as a relative time string (e.g., "2 hours ago")
 * Note: This is primarily handled server-side, but included for any client-side updates
 */
function formatTimeAgo(timestamp) {
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;
    
    if (diff < 60) return 'just now';
    if (diff < 3600) {
        const minutes = Math.floor(diff / 60);
        return `${minutes} minute${minutes !== 1 ? 's' : ''} ago`;
    }
    if (diff < 86400) {
        const hours = Math.floor(diff / 3600);
        return `${hours} hour${hours !== 1 ? 's' : ''} ago`;
    }
    if (diff < 604800) {
        const days = Math.floor(diff / 86400);
        return `${days} day${days !== 1 ? 's' : ''} ago`;
    }
    if (diff < 2592000) {
        const weeks = Math.floor(diff / 604800);
        return `${weeks} week${weeks !== 1 ? 's' : ''} ago`;
    }
    const months = Math.floor(diff / 2592000);
    return `${months} month${months !== 1 ? 's' : ''} ago`;
}
