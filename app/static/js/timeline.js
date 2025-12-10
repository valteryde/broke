/**
 * Timeline Page JavaScript
 * Handles filtering, view switching, calendar, and heatmap functionality
 */

document.addEventListener('DOMContentLoaded', () => {
    initFilters();
    initViewSwitcher();
    initCalendar();
    initHeatmap();
    initDateRangeFilter();
});

/**
 * Initialize filter buttons
 */
function initFilters() {
    const filterBtns = document.querySelectorAll('.filter-btn');
    const timelineEvents = document.querySelectorAll('.timeline-event');
    
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Update active state
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const filter = btn.dataset.filter;
            
            // Filter events
            timelineEvents.forEach(event => {
                if (filter === 'all' || event.dataset.type === filter) {
                    event.style.display = 'flex';
                } else {
                    event.style.display = 'none';
                }
            });
            
            // Update date headers visibility
            updateDateHeadersVisibility();
        });
    });
}

/**
 * Update visibility of date headers based on visible events
 */
function updateDateHeadersVisibility() {
    const dateHeaders = document.querySelectorAll('.timeline-date-header');
    
    dateHeaders.forEach(header => {
        // Find the next sibling events until the next date header
        let nextElement = header.nextElementSibling;
        let hasVisibleEvents = false;
        
        while (nextElement && !nextElement.classList.contains('timeline-date-header')) {
            if (nextElement.classList.contains('timeline-event') && 
                nextElement.style.display !== 'none') {
                hasVisibleEvents = true;
                break;
            }
            nextElement = nextElement.nextElementSibling;
        }
        
        header.style.display = hasVisibleEvents ? 'flex' : 'none';
    });
}

/**
 * Initialize view switcher (Timeline, Calendar, Summary)
 */
function initViewSwitcher() {
    const viewBtns = document.querySelectorAll('.view-btn');
    const timelineView = document.getElementById('timeline-view');
    const calendarView = document.getElementById('calendar-view');
    const summaryView = document.getElementById('summary-view');
    
    viewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Update active state
            viewBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const view = btn.dataset.view;
            
            // Show/hide views
            if (timelineView) timelineView.style.display = view === 'timeline' ? 'block' : 'none';
            if (calendarView) calendarView.style.display = view === 'calendar' ? 'block' : 'none';
            if (summaryView) summaryView.style.display = view === 'summary' ? 'block' : 'none';
        });
    });
}

/**
 * Initialize calendar view
 */
function initCalendar() {
    const calendarDays = document.getElementById('calendar-days');
    const monthYearLabel = document.getElementById('calendar-month-year');
    const prevBtn = document.getElementById('prev-month');
    const nextBtn = document.getElementById('next-month');
    
    if (!calendarDays) return;
    
    let currentDate = new Date();
    
    function renderCalendar(date) {
        const year = date.getFullYear();
        const month = date.getMonth();
        
        // Update header
        const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                           'July', 'August', 'September', 'October', 'November', 'December'];
        if (monthYearLabel) {
            monthYearLabel.textContent = `${monthNames[month]} ${year}`;
        }
        
        // Clear existing days
        calendarDays.innerHTML = '';
        
        // Get first day of month and total days
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const totalDays = lastDay.getDate();
        
        // Get starting day (0 = Sunday, adjust to Monday start)
        let startingDay = firstDay.getDay() - 1;
        if (startingDay < 0) startingDay = 6;
        
        // Add empty cells for days before the first
        for (let i = 0; i < startingDay; i++) {
            const prevMonthDay = new Date(year, month, 0 - (startingDay - i - 1));
            const dayElement = createDayElement(prevMonthDay, true);
            calendarDays.appendChild(dayElement);
        }
        
        // Add days of the month
        const today = new Date();
        for (let day = 1; day <= totalDays; day++) {
            const dayDate = new Date(year, month, day);
            const dayElement = createDayElement(dayDate, false);
            
            // Check if today
            if (dayDate.toDateString() === today.toDateString()) {
                dayElement.classList.add('today');
            }
            
            // Check for events on this day
            const dateKey = formatDateKey(dayDate);
            if (timelineData && timelineData.activityByDay && timelineData.activityByDay[dateKey]) {
                dayElement.classList.add('has-events');
                addEventDots(dayElement, dateKey);
            }
            
            calendarDays.appendChild(dayElement);
        }
        
        // Fill remaining cells
        const remainingCells = 42 - (startingDay + totalDays);
        for (let i = 1; i <= remainingCells; i++) {
            const nextMonthDay = new Date(year, month + 1, i);
            const dayElement = createDayElement(nextMonthDay, true);
            calendarDays.appendChild(dayElement);
        }
    }
    
    function createDayElement(date, isOtherMonth) {
        const dayElement = document.createElement('div');
        dayElement.className = 'calendar-day' + (isOtherMonth ? ' other-month' : '');
        dayElement.innerHTML = `<span class="day-number">${date.getDate()}</span>`;
        
        dayElement.addEventListener('click', () => {
            // Could implement day detail view here
            console.log('Clicked:', date.toDateString());
        });
        
        return dayElement;
    }
    
    function addEventDots(dayElement, dateKey) {
        const dotsContainer = document.createElement('div');
        dotsContainer.className = 'event-dots';
        
        // Check events for this day
        if (timelineData && timelineData.events) {
            const dayEvents = timelineData.events.filter(e => e.date_key === dateKey);
            const types = new Set(dayEvents.map(e => e.type));
            
            types.forEach(type => {
                if (['ticket', 'comment', 'error'].includes(type)) {
                    const dot = document.createElement('span');
                    dot.className = `event-dot ${type}`;
                    dotsContainer.appendChild(dot);
                }
            });
        }
        
        if (dotsContainer.children.length > 0) {
            dayElement.appendChild(dotsContainer);
        }
    }
    
    function formatDateKey(date) {
        return date.toISOString().split('T')[0];
    }
    
    // Navigation
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            currentDate.setMonth(currentDate.getMonth() - 1);
            renderCalendar(currentDate);
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            currentDate.setMonth(currentDate.getMonth() + 1);
            renderCalendar(currentDate);
        });
    }
    
    // Initial render
    renderCalendar(currentDate);
}

/**
 * Initialize activity heatmap
 */
function initHeatmap() {
    const heatmapContainer = document.getElementById('activity-heatmap');
    if (!heatmapContainer || !timelineData || !timelineData.activityByDay) return;
    
    const activityData = timelineData.activityByDay;
    
    // Clear container
    heatmapContainer.innerHTML = '';
    
    // Generate last 52 weeks of cells (364 days)
    const today = new Date();
    const cells = [];
    
    // Find max activity for scaling
    const maxActivity = Math.max(...Object.values(activityData), 1);
    
    // Create cells for each day, going back 52 weeks
    for (let i = 364; i >= 0; i--) {
        const date = new Date(today);
        date.setDate(date.getDate() - i);
        
        const dateKey = date.toISOString().split('T')[0];
        const activity = activityData[dateKey] || 0;
        
        // Calculate level (0-4)
        let level = 0;
        if (activity > 0) {
            level = Math.min(4, Math.ceil((activity / maxActivity) * 4));
        }
        
        const cell = document.createElement('div');
        cell.className = `heatmap-cell level-${level}`;
        cell.title = `${dateKey}: ${activity} activities`;
        
        cells.push(cell);
    }
    
    // Arrange in a grid - 7 rows (days of week) x 53 columns (weeks)
    // We need to align so that the current day of week is at the bottom
    const dayOfWeek = today.getDay() || 7; // Convert Sunday (0) to 7
    
    // Add cells to container
    cells.forEach(cell => {
        heatmapContainer.appendChild(cell);
    });
}

/**
 * Initialize date range filter
 */
function initDateRangeFilter() {
    const dateRangeSelect = document.getElementById('date-range-select');
    if (!dateRangeSelect) return;
    
    dateRangeSelect.addEventListener('change', () => {
        const days = dateRangeSelect.value;
        const currentUrl = new URL(window.location.href);
        
        if (days === 'all') {
            currentUrl.searchParams.delete('days');
        } else {
            currentUrl.searchParams.set('days', days);
        }
        
        // For now, just reload with the new parameter
        // A more sophisticated implementation would use AJAX
        window.location.href = currentUrl.toString();
    });
}

/**
 * Format timestamp to relative time
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

/**
 * Load more events (for infinite scroll or button click)
 */
function loadMoreEvents() {
    const loadMoreBtn = document.getElementById('load-more');
    if (!loadMoreBtn) return;
    
    loadMoreBtn.addEventListener('click', () => {
        // In a real implementation, this would fetch more events via AJAX
        // For now, we'll just show the additional events from timelineData
        loadMoreBtn.innerHTML = '<i class="ph ph-spinner"></i> Loading...';
        loadMoreBtn.disabled = true;
        
        setTimeout(() => {
            loadMoreBtn.parentElement.style.display = 'none';
        }, 1000);
    });
}

// Initialize load more
document.addEventListener('DOMContentLoaded', loadMoreEvents);
