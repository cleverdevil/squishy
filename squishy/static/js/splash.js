/**
 * Splash screen functionality for Squishy
 * 
 * Handles displaying and hiding the splash screen with animated logo and mascot.
 * Shows splash screen only once every 24 hours using a cookie.
 */

document.addEventListener('DOMContentLoaded', function() {
    // Get the splash screen element
    const splashScreen = document.getElementById('splash-screen');
    
    if (!splashScreen) {
        console.error('Splash screen element not found');
        return;
    }
    
    // Cookie management functions
    const getCookie = function(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : null;
    };
    
    const setCookie = function(name, value, expiryHours) {
        const date = new Date();
        date.setTime(date.getTime() + (expiryHours * 60 * 60 * 1000));
        const expires = "expires=" + date.toUTCString();
        document.cookie = name + "=" + value + ";" + expires + ";path=/";
    };
    
    // Check if we should show the splash screen
    const lastSplashTimestamp = getCookie('squishy_last_splash');
    const currentTime = new Date().getTime();
    
    // 24 hours in milliseconds = 24 * 60 * 60 * 1000 = 86400000
    const showSplash = !lastSplashTimestamp || (currentTime - parseInt(lastSplashTimestamp, 10)) > 86400000;
    
    if (showSplash) {
        // Show the splash screen
        splashScreen.style.display = 'flex';
        
        // Set cookie with current timestamp
        setCookie('squishy_last_splash', currentTime.toString(), 24);
        
        // Pick a random happy anvil
        const anvils = ['anvil-happy.png', 'anvil-happy-2.png'];
        const randomAnvil = anvils[Math.floor(Math.random() * anvils.length)];
        
        // Set the random anvil
        const mascotImg = document.querySelector('.splash-mascot img');
        if (mascotImg) {
            mascotImg.src = `/static/img/${randomAnvil}`;
        }
        
        // Hide the splash screen after a delay
        setTimeout(function() {
            // Add fade-out class to animate the disappearance
            splashScreen.classList.add('fade-out');
            
            // After animation completes, hide the element completely
            setTimeout(function() {
                splashScreen.style.display = 'none';
                
                // Optional: trigger any post-splash animations or actions
                document.body.classList.add('app-ready');
            }, 500); // Match this to the duration of the fadeOut animation
        }, 5000); // Show splash for 5 seconds
    } else {
        // Don't show splash screen, hide it immediately
        splashScreen.style.display = 'none';
    }
});