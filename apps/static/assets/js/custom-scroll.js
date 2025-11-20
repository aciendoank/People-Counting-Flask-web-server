// Override the Perfect Scrollbar initialization for the main sidebar
$(document).ready(function() {
    // Check if the old perfectScrollbar function is defined by the dashboard theme
    if ($.fn.perfectScrollbar) {
        // Unbind the old perfectScrollbar function from jQuery
        $.fn.perfectScrollbar = undefined;
    }

    // Now, find the element that needs the custom scrollbar
    // This part depends on how your HTML is structured. The example below is common.
    const sidebar = document.querySelector('.sidebar .sidebar-wrapper');

    // Check if the element exists and if the new PerfectScrollbar class is available
    if (sidebar && typeof PerfectScrollbar !== 'undefined') {
        new PerfectScrollbar(sidebar);
    }
});