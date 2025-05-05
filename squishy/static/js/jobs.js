/**
 * Squishy Jobs Page JavaScript
 * Handles job updates, log displays, auto-refreshing, and mascot animations
 */

// Use WebSockets for real-time updates
let pageReloadTimer = null;
const openLogStates = new Set();
const STORAGE_KEY = 'squishyOpenLogs';
const refreshIntervals = {};
let currentMascotState = null; // Track current state of mascot animation

// Mascot animation functions
function showMascot(status, jobId) {
    const mascotContainer = document.getElementById('mascot-container');
    const mascotImage = document.getElementById('mascot-image');
    
    if (!mascotContainer || !mascotImage) return;
    
    // Remove any existing animation classes
    mascotContainer.className = '';
    
    // Always show container
    mascotContainer.classList.remove('hidden');
    
    // Set appropriate image and animation based on status
    if (status === 'processing') {
        mascotImage.src = '/static/img/anvil-thinking.png';
        
        // Select a random entry direction
        const directions = ['mascot-processing', 'mascot-processing from-right', 'mascot-processing from-top', 'mascot-processing from-bottom'];
        const randomDirection = directions[Math.floor(Math.random() * directions.length)];
        
        mascotContainer.className = randomDirection;
        currentMascotState = { status: 'processing', jobId: jobId };
    } 
    else if (status === 'completed') {
        mascotImage.src = '/static/img/anvil-happy.png';
        mascotContainer.className = 'mascot-success';
        
        // Hide mascot after the animation completes
        currentMascotState = { status: 'completed', jobId: jobId };
        setTimeout(() => {
            // Only hide if this is still the current animation
            if (currentMascotState && currentMascotState.status === 'completed' && currentMascotState.jobId === jobId) {
                hideMascot();
            }
        }, 3000);
    } 
    else if (status === 'failed') {
        mascotImage.src = '/static/img/anvil-sad.png';
        mascotContainer.className = 'mascot-failed';
        
        // Hide mascot after a delay
        currentMascotState = { status: 'failed', jobId: jobId };
        setTimeout(() => {
            // Only hide if this is still the current animation
            if (currentMascotState && currentMascotState.status === 'failed' && currentMascotState.jobId === jobId) {
                hideMascot();
            }
        }, 4000);
    }
}

function hideMascot() {
    const mascotContainer = document.getElementById('mascot-container');
    if (mascotContainer) {
        mascotContainer.classList.add('hidden');
        currentMascotState = null;
    }
}

// Initialize the page
function initializePage() {
    if (pageReloadTimer) {
        clearTimeout(pageReloadTimer);
    }
    
    // Check if there are any processing jobs to show mascot
    const processingJobs = document.querySelectorAll('td.status-processing');
    if (processingJobs.length > 0) {
        // Get the job ID from the first processing job
        const jobId = processingJobs[0].getAttribute('data-job-id');
        showMascot('processing', jobId);
    }

    // Load saved open log states from localStorage
    try {
        const savedOpenLogs = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        savedOpenLogs.forEach(jobId => openLogStates.add(jobId));

        // Restore open logs from localStorage
        openLogStates.forEach(jobId => {
            const logsRow = document.getElementById(`logs-${jobId}`);
            const toggleButton = document.querySelector(`.logs-circle-button[data-job-id="${jobId}"]`);

            if (logsRow && toggleButton) {
                logsRow.classList.remove('hidden');
                logsRow.style.display = 'table-row'; // Table rows need display:table-row
                toggleButton.title = 'Hide Log';

                // Load the logs content
                loadJobLogs(jobId);

                // Scroll to bottom after a delay to ensure content is loaded
                setTimeout(() => {
                    const logsEl = document.getElementById(`logs-content-${jobId}`);
                    if (logsEl) scrollToBottom(logsEl);
                }, 300);
            }
        });
    } catch (e) {
        console.error('Error loading saved log states:', e);
    }

    // Set up WebSocket event listener for job updates
    document.addEventListener('squishy:job_update', function(event) {
        const jobData = event.detail;
        if (jobData && jobData.id) {
            updateJobElement(jobData);
        }
    });

    // Do an initial fetch of all jobs to ensure we have the latest data
    fetch('/api/jobs')
        .then(response => response.json())
        .then(data => {
            // Get a list of all active job IDs
            const activeJobIds = data.jobs.map(job => job.id);

            // Remove any open log states for jobs that no longer exist
            [...openLogStates].forEach(jobId => {
                if (!activeJobIds.includes(jobId)) {
                    openLogStates.delete(jobId);
                    saveOpenLogStates();
                }
            });

            // Update job data for each job
            data.jobs.forEach(job => {
                updateJobElement(job);
            });
        })
        .catch(error => {
            console.error('Error fetching initial job data:', error);
        });

    // Set up our own page reload every 60 seconds as a fallback
    // This is less important now with WebSockets but still good for reliability
    pageReloadTimer = setTimeout(function() {
        saveOpenLogStates();
        location.reload();
    }, 60000); // Increased from 30s to 60s since we're using WebSockets
}

// Save open log states to localStorage
function saveOpenLogStates() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...openLogStates]));
    } catch (e) {
        console.error('Error saving log states:', e);
    }
}

// Update a specific job's UI elements
function updateJobElement(job) {
    // Find the status element for this job - it might be in any of the three tables
    const statusEl = document.querySelector(`tr td.status[data-job-id="${job.id}"]`);
    if (!statusEl) return;

    // Check if the job status has changed
    const currentStatus = statusEl.className.split(' ').find(cls => cls.startsWith('status-')).replace('status-', '');
    if (currentStatus !== job.status) {
        // Show appropriate mascot animation when a job changes status
        if (job.status === 'completed' || job.status === 'failed') {
            showMascot(job.status, job.id);
        }
        
        // Status has changed - we need to reload the page to move the job to the correct table
        saveOpenLogStates();
        
        // Give a little delay to see the animation before reload
        setTimeout(() => {
            location.reload();
        }, 2000);
        return;
    }

    // Update the progress if it's a processing job
    const progressContainer = document.querySelector(`tr[data-job-id="${job.id}"] .progress-container`);
    if (progressContainer && job.status === 'processing') {
        const progressBar = progressContainer.querySelector('progress');
        const progressText = progressContainer.querySelector('.progress-text');
        const progressTime = progressContainer.querySelector('.progress-time');

        if (progressBar) progressBar.value = job.progress;
        if (progressText) progressText.textContent = `${Math.round(job.progress * 100)}%`;

        // If we have timing data, update it
        if (progressTime && job.current_time && job.duration) {
            progressTime.textContent = `${Math.round(job.current_time)}s / ${Math.round(job.duration)}s`;
        }
    }

    // If this job has logs open and we have ffmpeg_logs in the update, update the logs display
    if (openLogStates.has(job.id) && job.ffmpeg_logs && job.ffmpeg_logs.length > 0) {
        const logsContentEl = document.getElementById(`logs-content-${job.id}`);
        if (logsContentEl) {
            // Check if we should auto-scroll based on whether user is already at bottom
            const wasAtBottom = isScrolledToBottom(logsContentEl);
            
            // Get current logs
            let currentLogs = logsContentEl.textContent || '';
            if (!currentLogs.includes(job.ffmpeg_logs[job.ffmpeg_logs.length - 1])) {
                // Append new logs if they're not already there
                job.ffmpeg_logs.forEach(logLine => {
                    if (!currentLogs.includes(logLine)) {
                        currentLogs += (currentLogs ? '\n' : '') + logLine;
                    }
                });
                
                // Update logs content
                logsContentEl.textContent = currentLogs;
                
                // Auto-scroll if we were already at bottom
                if (wasAtBottom) {
                    setTimeout(() => scrollToBottom(logsContentEl), 10);
                }
            }
        } else {
            // If we can't find the logs content element but logs are open, do a full refresh
            loadJobLogs(job.id);
        }
    } else if (openLogStates.has(job.id) && (!job.ffmpeg_logs || job.ffmpeg_logs.length === 0)) {
        // If logs are open but we don't have logs in the update, do a full refresh
        loadJobLogs(job.id);
    }
}

// Load job logs
function loadJobLogs(jobId) {
    const logsEl = document.getElementById(`logs-content-${jobId}`);
    const shouldAutoScroll = document.querySelector(`.auto-refresh-logs[data-job-id="${jobId}"]`)?.checked;
    const wasAtBottom = isScrolledToBottom(logsEl);

    fetch(`/api/jobs/${jobId}/logs`)
        .then(response => response.json())
        .then(data => {
            // Update command
            const commandEl = document.getElementById(`command-${jobId}`);
            commandEl.textContent = data.ffmpeg_command || 'Command not available';

            // Update logs
            logsEl.textContent = data.ffmpeg_logs.join('\n') || 'No logs available';

            // Auto-scroll to bottom if auto-refresh is enabled or user was already at bottom
            if (shouldAutoScroll || wasAtBottom) {
                setTimeout(() => scrollToBottom(logsEl), 10);
            }
        })
        .catch(error => {
            console.error('Error fetching logs:', error);
        });
}

// Check if element is scrolled to bottom
function isScrolledToBottom(el) {
    // Allow a small buffer (5px) to account for rounding errors
    return el.scrollHeight - el.clientHeight - el.scrollTop <= 5;
}

// Scroll element to bottom
function scrollToBottom(el) {
    el.scrollTop = el.scrollHeight;
}

// Set up event listeners when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializePage();
    
    // Toggle log visibility
    document.querySelectorAll('.logs-circle-button').forEach(button => {
        button.addEventListener('click', function() {
            const jobId = this.getAttribute('data-job-id');
            const logsRow = document.getElementById(`logs-${jobId}`);

            // Toggle visibility
            if (logsRow.classList.contains('hidden')) {
                logsRow.classList.remove('hidden');
                logsRow.style.display = 'table-row'; // Table rows need display:table-row
                this.title = 'Hide Log';

                // Load logs and scroll to bottom on initial load
                loadJobLogs(jobId);

                // After logs are loaded, ensure we scroll to bottom (for the initial view)
                setTimeout(() => {
                    const logsEl = document.getElementById(`logs-content-${jobId}`);
                    scrollToBottom(logsEl);
                }, 300);

                openLogStates.add(jobId);
                saveOpenLogStates(); // Save the state change
            } else {
                logsRow.classList.add('hidden');
                this.title = 'Show Log';
                openLogStates.delete(jobId);
                saveOpenLogStates(); // Save the state change
            }
        });
    });

    // Auto-refresh logs for processing jobs
    document.querySelectorAll('.auto-refresh-logs').forEach(checkbox => {
        const jobId = checkbox.getAttribute('data-job-id');

        checkbox.addEventListener('change', function() {
            if (this.checked) {
                // Start auto-refresh
                refreshIntervals[jobId] = setInterval(() => {
                    if (openLogStates.has(jobId)) {
                        loadJobLogs(jobId);
                    }
                }, 3000);

                // Immediately scroll to bottom when auto-refresh is enabled
                const logsEl = document.getElementById(`logs-content-${jobId}`);
                scrollToBottom(logsEl);
            } else {
                // Stop auto-refresh
                clearInterval(refreshIntervals[jobId]);
                delete refreshIntervals[jobId];
            }
        });

        // Initialize auto-refresh if checked
        if (checkbox.checked) {
            refreshIntervals[jobId] = setInterval(() => {
                if (openLogStates.has(jobId)) {
                    loadJobLogs(jobId);
                }
            }, 3000);
        }
    });
});