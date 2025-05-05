/**
 * Mobile Navigation Script
 * Handles the mobile menu toggle functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const mobileMenuToggle = document.querySelector('.mobile-menu-toggle');
    const navMenu = document.querySelector('.nav-menu');
    
    if (mobileMenuToggle && navMenu) {
        // Toggle menu when hamburger button is clicked
        mobileMenuToggle.addEventListener('click', function() {
            navMenu.classList.toggle('open');
            
            // Toggle aria-expanded attribute for accessibility
            const isExpanded = navMenu.classList.contains('open');
            mobileMenuToggle.setAttribute('aria-expanded', isExpanded);
            
            // Animation for hamburger to X
            const bars = mobileMenuToggle.querySelectorAll('.menu-bar');
            if (isExpanded) {
                // Transform to X
                if (bars[0]) bars[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
                if (bars[1]) bars[1].style.opacity = '0';
                if (bars[2]) bars[2].style.transform = 'rotate(-45deg) translate(6px, -6px)';
            } else {
                // Reset to hamburger
                if (bars[0]) bars[0].style.transform = 'none';
                if (bars[1]) bars[1].style.opacity = '1';
                if (bars[2]) bars[2].style.transform = 'none';
            }
        });
        
        // Close menu when clicking anywhere else on the page
        document.addEventListener('click', function(event) {
            if (!navMenu.contains(event.target) && 
                !mobileMenuToggle.contains(event.target) && 
                navMenu.classList.contains('open')) {
                
                navMenu.classList.remove('open');
                mobileMenuToggle.setAttribute('aria-expanded', false);
                
                // Reset hamburger icon
                const bars = mobileMenuToggle.querySelectorAll('.menu-bar');
                if (bars[0]) bars[0].style.transform = 'none';
                if (bars[1]) bars[1].style.opacity = '1';
                if (bars[2]) bars[2].style.transform = 'none';
            }
        });
        
        // Close menu when ESC key is pressed
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' && navMenu.classList.contains('open')) {
                navMenu.classList.remove('open');
                mobileMenuToggle.setAttribute('aria-expanded', false);
                
                // Reset hamburger icon
                const bars = mobileMenuToggle.querySelectorAll('.menu-bar');
                if (bars[0]) bars[0].style.transform = 'none';
                if (bars[1]) bars[1].style.opacity = '1';
                if (bars[2]) bars[2].style.transform = 'none';
            }
        });
    }
});