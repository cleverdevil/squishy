document.addEventListener('DOMContentLoaded', function() {
    // Load basic technical info for badges immediately
    loadTechnicalInfo();
    
    // Helper function to create a table row
    function createTableRow(label, value) {
        const row = document.createElement('tr');
        const th = document.createElement('th');
        const td = document.createElement('td');
        
        th.textContent = label;
        td.textContent = value;
        
        row.appendChild(th);
        row.appendChild(td);
        
        return row;
    }
    
    // Load technical information via API
    function loadTechnicalInfo() {
        // Get media ID from a data attribute or from the URL
        const mediaId = document.querySelector('.media-detail').dataset.mediaId;
        
        fetch(`/api/media/${mediaId}/technical_info`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load technical information');
                }
                return response.json();
            })
            .then(data => {
                // Process the technical information
                
                // First, update basic info and badges
                updateBasicInfo(data);
                
                // Then update the detailed technical information
                updateTechnicalInfo(data);
                
                // Hide loading indicator and show content
                document.getElementById('tech-info-loading').style.display = 'none';
                const techInfoContainer = document.getElementById('technical-info-container');
                techInfoContainer.style.display = 'block';
                techInfoContainer.classList.add('fade-in');
            })
            .catch(error => {
                console.error('Error:', error);
                document.getElementById('tech-info-loading').innerHTML = `
                    <p>Error loading technical information: ${error.message}</p>
                    <button onclick="loadTechnicalInfo()" class="button">Retry</button>
                `;
                
                // Show notification error
                showNotification('Failed to load technical information. Please try again.', 'error');
            });
    }
    
    // Update basic info and badges
    function updateBasicInfo(data) {
        // Update file size and duration in description (if no overview)
        const durationInfo = document.getElementById('duration-info');
        const fileSizeInfo = document.getElementById('file-size-info');
        
        if (durationInfo) {
            const duration = data.format?.duration || 0;
            durationInfo.textContent = `${(duration / 60).toFixed(1)} minutes`;
        }
        
        if (fileSizeInfo) {
            fileSizeInfo.textContent = data.formatted_file_size || 'Unknown';
        }
        
        // Update resolution badge
        const resolutionBadge = document.getElementById('resolution-badge');
        if (data.basic_info?.has_resolution_badge) {
            resolutionBadge.textContent = data.basic_info.resolution_badge;
            resolutionBadge.style.display = 'inline-block';
        }
        
        // Update HDR badge
        const hdrBadge = document.getElementById('hdr-badge');
        if (data.basic_info?.has_hdr) {
            hdrBadge.textContent = data.basic_info.hdr_type;
            hdrBadge.style.display = 'inline-block';
        }
    }
    
    // Update detailed technical information
    function updateTechnicalInfo(data) {
        // Update file information
        document.getElementById('file-size-value').textContent = data.formatted_file_size || 'Unknown';
        document.getElementById('format-name').textContent = data.format?.format_name || 'Unknown';
        document.getElementById('duration-value').textContent = `${((data.format?.duration || 0) / 60).toFixed(2)} minutes`;
        document.getElementById('bitrate-value').textContent = `${((data.format?.bit_rate || 0) / 1000000).toFixed(2)} Mbps`;
        
        // Update video information
        if (data.video && data.video.length > 0) {
            const videoSection = document.getElementById('video-section');
            const videoContainer = document.getElementById('video-info-container');
            videoContainer.innerHTML = '';
            
            data.video.forEach((video, index) => {
                const table = document.createElement('table');
                
                // Add rows for each video property
                table.appendChild(createTableRow('Codec', `${video.codec} (${video.codec_description})`));
                table.appendChild(createTableRow('Resolution', `${video.width}x${video.height}`));
                table.appendChild(createTableRow('Aspect Ratio', video.aspect_ratio || 'Unknown'));
                table.appendChild(createTableRow('Frame Rate', `${video.frame_rate} fps`));
                table.appendChild(createTableRow('Bit Depth', `${video.bit_depth} bit`));
                table.appendChild(createTableRow('Pixel Format', video.pixel_format || 'Unknown'));
                table.appendChild(createTableRow('Profile', video.profile || 'Unknown'));
                
                // Add color information if available
                if (video.color_space || video.color_transfer || video.color_primaries) {
                    table.appendChild(createTableRow('Color Space', video.color_space || 'Unknown'));
                    table.appendChild(createTableRow('Color Transfer', video.color_transfer || 'Unknown'));
                    table.appendChild(createTableRow('Color Primaries', video.color_primaries || 'Unknown'));
                }
                
                videoContainer.appendChild(table);
                
                // Add separator if not the last item
                if (index < data.video.length - 1) {
                    const separator = document.createElement('div');
                    separator.className = 'separator';
                    videoContainer.appendChild(separator);
                }
            });
            
            videoSection.style.display = 'block';
        }
        
        // Update HDR information
        if (data.hdr_info) {
            const hdrSection = document.getElementById('hdr-section');
            const hdrTable = document.getElementById('hdr-info-table');
            hdrTable.innerHTML = '';
            
            // Add rows for each HDR property
            hdrTable.appendChild(createTableRow('HDR Type', data.hdr_info.type || 'Unknown'));
            
            if (data.hdr_info.dv_profile) {
                hdrTable.appendChild(createTableRow('Dolby Vision Profile', data.hdr_info.dv_profile));
            }
            
            if (data.hdr_info.dv_level) {
                hdrTable.appendChild(createTableRow('Dolby Vision Level', data.hdr_info.dv_level));
            }
            
            if (data.hdr_info.master_display) {
                hdrTable.appendChild(createTableRow('Master Display', data.hdr_info.master_display));
            }
            
            if (data.hdr_info.max_content) {
                hdrTable.appendChild(createTableRow('Max Content Light Level', data.hdr_info.max_content));
            }
            
            if (data.hdr_info.max_average) {
                hdrTable.appendChild(createTableRow('Max Average Light Level', data.hdr_info.max_average));
            }
            
            hdrSection.style.display = 'block';
        }
        
        // Update audio information
        if (data.audio && data.audio.length > 0) {
            const audioSection = document.getElementById('audio-section');
            const audioContainer = document.getElementById('audio-info-container');
            audioContainer.innerHTML = '';
            
            data.audio.forEach((audio, index) => {
                const table = document.createElement('table');
                
                // Add rows for each audio property
                table.appendChild(createTableRow('Codec', `${audio.codec} (${audio.codec_description})`));
                table.appendChild(createTableRow('Channels', `${audio.channels} (${audio.channel_layout})`));
                table.appendChild(createTableRow('Sample Rate', `${audio.sample_rate} Hz`));
                
                if (audio.bit_rate) {
                    table.appendChild(createTableRow('Bit Rate', `${(audio.bit_rate / 1000).toFixed(2)} kbps`));
                }
                
                if (audio.language) {
                    table.appendChild(createTableRow('Language', audio.language));
                }
                
                if (audio.title) {
                    table.appendChild(createTableRow('Title', audio.title));
                }
                
                audioContainer.appendChild(table);
                
                // Add separator if not the last item
                if (index < data.audio.length - 1) {
                    const separator = document.createElement('div');
                    separator.className = 'separator';
                    audioContainer.appendChild(separator);
                }
            });
            
            audioSection.style.display = 'block';
        }
        
        // Update subtitle information
        if (data.subtitle && data.subtitle.length > 0) {
            const subtitleSection = document.getElementById('subtitle-section');
            const subtitleContainer = document.getElementById('subtitle-info-container');
            subtitleContainer.innerHTML = '';
            
            data.subtitle.forEach((subtitle, index) => {
                const table = document.createElement('table');
                
                // Add rows for each subtitle property
                table.appendChild(createTableRow('Codec', subtitle.codec));
                
                if (subtitle.language) {
                    table.appendChild(createTableRow('Language', subtitle.language));
                }
                
                if (subtitle.title) {
                    table.appendChild(createTableRow('Title', subtitle.title));
                }
                
                subtitleContainer.appendChild(table);
                
                // Add separator if not the last item
                if (index < data.subtitle.length - 1) {
                    const separator = document.createElement('div');
                    separator.className = 'separator';
                    subtitleContainer.appendChild(separator);
                }
            });
            
            subtitleSection.style.display = 'block';
        }
    }
});