document.addEventListener('DOMContentLoaded', function() {
    console.log('Show detail page loaded');
    
    // Technical Info Button Click Handler
    document.querySelectorAll('.tech-info-btn').forEach(button => {
        button.addEventListener('click', function() {
            const episodeId = this.getAttribute('data-episode-id');
            const episodePath = this.getAttribute('data-path');
            
            // Show modal
            const modal = document.getElementById('techInfoModal');
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
            
            // Show loading, hide content
            const loadingContainer = modal.querySelector('.loading-container');
            const techInfoContent = document.getElementById('techInfoContent');
            
            loadingContainer.style.display = 'flex';
            techInfoContent.classList.add('hidden');
            techInfoContent.innerHTML = '';
            
            // Fetch technical info
            fetch(`/api/media/${episodeId}/technical_info`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`API error: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    // Generate content
                    techInfoContent.innerHTML = generateTechInfoContent(data, episodePath);
                    
                    // Hide loading, show content
                    loadingContainer.classList.add('hidden');
                    techInfoContent.classList.remove('hidden');
                })
                .catch(error => {
                    // Show error message
                    techInfoContent.innerHTML = `
                        <div class="error-message">
                            <p>Error loading technical information: ${error.message}</p>
                            <p>Please try again later.</p>
                        </div>
                    `;
                    
                    loadingContainer.classList.add('hidden');
                    techInfoContent.classList.remove('hidden');
                    
                    // Show notification if available
                    if (typeof showNotification === 'function') {
                        showNotification('Failed to load technical information.', 'error');
                    }
                });
        });
    });
    
    // Squish Button Click Handler
    document.querySelectorAll('.squish-btn').forEach(button => {
        button.addEventListener('click', function() {
            const episodeId = this.getAttribute('data-episode-id');
            const episodeTitle = this.getAttribute('data-episode-title');
            
            // Show modal
            const modal = document.getElementById('squishModal');
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
            
            // Update form action
            const form = document.getElementById('squishForm');
            form.action = form.action.replace('placeholder', episodeId);
            
            // Update modal title if needed
            const modalTitle = document.getElementById('squishModalTitle');
            if (modalTitle && episodeTitle) {
                modalTitle.textContent = `Squish: ${episodeTitle}`;
            }
        });
    });
    
    
    // Modal Close Handlers
    document.querySelectorAll('.close-modal').forEach(closeBtn => {
        closeBtn.addEventListener('click', function() {
            // Find the parent modal and hide it
            const modal = this.closest('.modal');
            if (modal) {
                modal.classList.add('hidden');
            }
        });
    });
    
    // Close modal when clicking outside
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(event) {
            if (event.target === this) {
                this.style.display = 'none';
            }
        });
    });
    
    // Submit handler for the squish form - no need to override, let the form submit normally
    const squishForm = document.getElementById('squishForm');
    if (squishForm) {
        squishForm.addEventListener('submit', function(event) {
            // Don't prevent default, let the form submit normally to ui.transcode
            
            // Close the modal after a brief delay
            setTimeout(() => {
                document.getElementById('squishModal').style.display = 'none';
            }, 100);
            
            // Show notification
            if (typeof showNotification === 'function') {
                const profileName = this.querySelector('select').options[this.querySelector('select').selectedIndex].text;
                showNotification(`Starting transcoding with profile: ${profileName}`, 'info');
            }
        });
    }
});

/**
 * Generate HTML content for technical information display
 */
function generateTechInfoContent(data, episodePath) {
    let html = '';
    
    // File Information section
    html += `
        <div class="tech-section">
            <h4>File Information</h4>
            <div class="tech-card">
                <table>
                    <tbody>
                        <tr>
                            <th>File Path</th>
                            <td>${episodePath || data.format?.filename || 'Unknown'}</td>
                        </tr>
                        <tr>
                            <th>File Size</th>
                            <td>${data.formatted_file_size || 'Unknown'}</td>
                        </tr>
                        <tr>
                            <th>Format</th>
                            <td>${data.format?.format_name || 'Unknown'}</td>
                        </tr>
                        <tr>
                            <th>Duration</th>
                            <td>${formatDuration(data.format?.duration || 0)}</td>
                        </tr>
                        <tr>
                            <th>Bitrate</th>
                            <td>${formatBitrate(data.format?.bit_rate || 0)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;
    
    // Video section
    if (data.video && data.video.length > 0) {
        html += `
            <div class="tech-section">
                <h4>Video</h4>
                <div class="tech-card">
        `;
        
        data.video.forEach((video, index) => {
            if (index > 0) html += '<div class="separator"></div>';
            
            html += `
                <table>
                    <tbody>
                        <tr>
                            <th>Codec</th>
                            <td>${video.codec || 'Unknown'} ${video.codec_description ? `(${video.codec_description})` : ''}</td>
                        </tr>
                        <tr>
                            <th>Resolution</th>
                            <td>${video.width || '?'}x${video.height || '?'}</td>
                        </tr>
                        <tr>
                            <th>Frame Rate</th>
                            <td>${video.frame_rate || 'Unknown'} fps</td>
                        </tr>
                        <tr>
                            <th>Bit Depth</th>
                            <td>${video.bit_depth || 'Unknown'} bit</td>
                        </tr>
                    </tbody>
                </table>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    }
    
    // HDR section
    if (data.hdr_info) {
        html += `
            <div class="tech-section">
                <h4>HDR Information</h4>
                <div class="tech-card">
                    <table>
                        <tbody>
                            <tr>
                                <th>HDR Type</th>
                                <td>${data.hdr_info.type || 'Unknown'}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }
    
    // Audio section
    if (data.audio && data.audio.length > 0) {
        html += `
            <div class="tech-section">
                <h4>Audio</h4>
                <div class="tech-card">
        `;
        
        data.audio.forEach((audio, index) => {
            if (index > 0) html += '<div class="separator"></div>';
            
            html += `
                <table>
                    <tbody>
                        <tr>
                            <th>Codec</th>
                            <td>${audio.codec || 'Unknown'}</td>
                        </tr>
                        <tr>
                            <th>Channels</th>
                            <td>${audio.channels || 'Unknown'} ${audio.channel_layout ? `(${audio.channel_layout})` : ''}</td>
                        </tr>
            `;
            
            if (audio.language) {
                html += `
                        <tr>
                            <th>Language</th>
                            <td>${audio.language}</td>
                        </tr>
                `;
            }
            
            html += `
                    </tbody>
                </table>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    }
    
    // Subtitle section
    if (data.subtitle && data.subtitle.length > 0) {
        html += `
            <div class="tech-section">
                <h4>Subtitles</h4>
                <div class="tech-card">
        `;
        
        data.subtitle.forEach((subtitle, index) => {
            if (index > 0) html += '<div class="separator"></div>';
            
            html += `
                <table>
                    <tbody>
                        <tr>
                            <th>Codec</th>
                            <td>${subtitle.codec || 'Unknown'}</td>
                        </tr>
            `;
            
            if (subtitle.language) {
                html += `
                        <tr>
                            <th>Language</th>
                            <td>${subtitle.language}</td>
                        </tr>
                `;
            }
            
            if (subtitle.title) {
                html += `
                        <tr>
                            <th>Title</th>
                            <td>${subtitle.title}</td>
                        </tr>
                `;
            }
            
            html += `
                    </tbody>
                </table>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    }
    
    return html;
}

/**
 * Format seconds into hours, minutes, seconds
 */
function formatDuration(seconds) {
    if (!seconds) return 'Unknown';
    
    const totalMinutes = Math.floor(seconds / 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    const remainingSeconds = Math.floor(seconds % 60);
    
    if (hours > 0) {
        return `${hours}h ${minutes}m ${remainingSeconds}s`;
    } else {
        return `${minutes}m ${remainingSeconds}s`;
    }
}

/**
 * Format bitrate in appropriate units
 */
function formatBitrate(bitrate) {
    if (!bitrate) return 'Unknown';
    
    if (bitrate >= 1000000) {
        return `${(bitrate / 1000000).toFixed(2)} Mbps`;
    } else {
        return `${(bitrate / 1000).toFixed(2)} Kbps`;
    }
}