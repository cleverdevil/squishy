// Custom tooltips implementation for Squishy
document.addEventListener('DOMContentLoaded', function() {
    // Create tooltip container once
    const tooltipContainer = document.createElement('div');
    tooltipContainer.className = 'tooltip-container';
    document.body.appendChild(tooltipContainer);
    
    // Add event listeners to all elements with data-tooltip attribute
    document.querySelectorAll('[data-tooltip]').forEach(element => {
        element.addEventListener('mouseenter', showTooltip);
        element.addEventListener('mouseleave', hideTooltip);
        element.addEventListener('mousemove', moveTooltip);
    });
    
    function showTooltip(e) {
        const tooltip = e.target.closest('[data-tooltip]');
        if (!tooltip) return;
        
        const tooltipText = tooltip.getAttribute('data-tooltip');
        tooltipContainer.textContent = tooltipText;
        tooltipContainer.style.display = 'block';
        
        // Position tooltip near cursor
        moveTooltip(e);
    }
    
    function hideTooltip() {
        tooltipContainer.style.display = 'none';
    }
    
    function moveTooltip(e) {
        // Offset above the cursor
        const x = e.clientX;
        const y = e.clientY - 40; // Position above cursor
        
        // Update tooltip position
        tooltipContainer.style.left = `${x}px`;
        tooltipContainer.style.top = `${y}px`;
    }
});