/**
 * Notification system for Squishy
 */
const notificationSystem = {
    container: null,
    notificationCount: 0,
    
    init: function() {
        this.container = document.getElementById('notification-container');
        
        // Process flashed messages if any
        this.processFlashedMessages();
    },
    
    processFlashedMessages: function() {
        // Get all flashed messages from the server-side (if any)
        const flashedMessages = FLASHED_MESSAGES;
        
        if (flashedMessages && flashedMessages.length > 0) {
            flashedMessages.forEach(flash => {
                const category = flash[0] || 'info';
                const message = flash[1];
                this.show(message, category);
            });
        }
    },
    
    show: function(message, type = 'info', timeout = 5000) {
        const id = `notification-${this.notificationCount++}`;
        const notification = document.createElement('div');
        notification.id = id;
        notification.className = `notification ${type}`;
        notification.style.display = 'block';
        
        // Choose mascot image based on notification type
        let mascotImage = 'anvil-thinking.png';
        if (type === 'success') {
            mascotImage = Math.random() > 0.5 ? 'anvil-happy.png' : 'anvil-happy-2.png';
        } else if (type === 'error') {
            mascotImage = 'anvil-sad.png';
        } else if (type === 'warning') {
            mascotImage = 'anvil-surprised.png';
        }
        
        notification.innerHTML = `
            <div class="notification-content">
                <div class="notification-mascot">
                    <img src="/static/img/${mascotImage}" alt="Squishy mascot">
                </div>
                <span class="notification-message">${message}</span>
            </div>
        `;
        
        this.container.appendChild(notification);
        
        // Auto-hide after timeout
        if (timeout > 0) {
            setTimeout(() => {
                this.hide(id);
            }, timeout);
        }
        
        return id;
    },
    
    hide: function(id) {
        const notification = document.getElementById(id);
        if (notification) {
            notification.style.animation = 'fade-out 0.5s forwards';
            setTimeout(() => {
                notification.remove();
            }, 500);
        }
    },
    
    // Special method for scan notifications which have different behavior
    updateScanNotification: function(data) {
        const scanNotificationEl = document.getElementById('scan-notification');
        const contentEl = scanNotificationEl.querySelector('.notification-content');
        
        if (data.in_progress) {
            // Format message based on the source
            let source = data.source ? data.source.charAt(0).toUpperCase() + data.source.slice(1) : 'Media';
            let message = `${source} scan in progress...`;
            
            // Update HTML with mascot
            contentEl.innerHTML = `
                <div class="notification-mascot">
                    <img src="/static/img/anvil-thinking.png" alt="Squishy mascot">
                </div>
                <span class="notification-message">${message}</span>
            `;
            
            // Show notification
            scanNotificationEl.classList.remove('hidden');
        } else {
            // If completed recently, show completed message
            if (data.completed_at && (Date.now() / 1000 - data.completed_at < 5)) {
                let source = data.source ? data.source.charAt(0).toUpperCase() + data.source.slice(1) : 'Media';
                let message = `${source} scan complete! Found ${data.item_count} items.`;
                
                // Choose a happy mascot image
                let mascotImage = Math.random() > 0.5 ? 'anvil-happy.png' : 'anvil-happy-2.png';
                
                // Update HTML with mascot
                contentEl.innerHTML = `
                    <div class="notification-mascot">
                        <img src="/static/img/${mascotImage}" alt="Squishy mascot">
                    </div>
                    <span class="notification-message">${message}</span>
                `;
                
                scanNotificationEl.classList.remove('hidden');
                
                // Hide after 3 seconds
                setTimeout(() => {
                    scanNotificationEl.classList.add('hidden');
                }, 3000);
            } else {
                // No active scan and not recently completed
                scanNotificationEl.classList.add('hidden');
            }
        }
    }
};

// Initialize socket connection and event listeners
function initializeSocketConnection() {
    // Connect to SocketIO server
    const socket = io();
    
    // Listen for connection events
    socket.on('connect', function() {
        console.log('Connected to Squishy WebSocket server');
    });
    
    socket.on('disconnect', function() {
        console.log('Disconnected from Squishy WebSocket server');
    });
    
    // Handle scan status updates
    socket.on('scan_status', function(data) {
        notificationSystem.updateScanNotification(data);
    });
    
    // Handle job updates
    socket.on('job_update', function(data) {
        // This event can be used in jobs.html and elsewhere to update job status
        // We'll dispatch a custom event so other pages can listen
        const event = new CustomEvent('squishy:job_update', { detail: data });
        document.dispatchEvent(event);
        
        // Show a notification for completed or failed jobs
        if (data.status === 'completed') {
            notificationSystem.show(`Job completed: ${data.title || 'Media transcoded successfully'}`, 'success');
        } else if (data.status === 'failed') {
            notificationSystem.show(`Job failed: ${data.error_message || 'Transcoding failed'}`, 'error');
        }
    });
    
    // Get initial scan status
    fetch('/api/scan/status')
        .then(response => response.json())
        .then(data => {
            notificationSystem.updateScanNotification(data);
        })
        .catch(error => {
            console.error('Error fetching initial scan status:', error);
        });
}

// Global function to show notifications from anywhere in the app
function showNotification(message, type = 'info', timeout = 5000) {
    return notificationSystem.show(message, type, timeout);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize notification system
    notificationSystem.init();
    
    // Initialize socket connection
    initializeSocketConnection();
});