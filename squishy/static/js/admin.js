function toggleSourceFields() {
    // Hide all source fields first
    document.querySelectorAll('.source-fields').forEach(function(el) {
        el.style.display = 'none';
    });

    // Show the selected source fields
    var selectedSource = document.querySelector('input[name="source"]:checked').value;
    document.getElementById(selectedSource + 'Fields').style.display = 'block';

    // Update the scan type in the hidden form
    document.getElementById('scan_type').value = selectedSource;
}

function toggleHwDeviceField() {
    const hwAccelSelect = document.getElementById('hw_accel');
    const hwDeviceGroup = document.getElementById('hw_device_group');
    
    // Show device field only for methods that need it
    if (hwAccelSelect.value === 'nvenc' || hwAccelSelect.value === 'cuda' || hwAccelSelect.value === 'vaapi') {
        hwDeviceGroup.style.display = 'block';
    } else {
        hwDeviceGroup.style.display = 'none';
    }
}

function scanMedia() {
    var selectedSource = document.querySelector('input[name="source"]:checked').value;

    // Check if necessary credentials are provided for media servers
    if (selectedSource === 'jellyfin') {
        var jellyfinUrl = document.getElementById('jellyfin_url').value;
        var jellyfinApiKey = document.getElementById('jellyfin_api_key').value;
        if (!jellyfinUrl || !jellyfinApiKey) {
            alert('Please provide Jellyfin URL and API Key before scanning.');
            return;
        }
    } else if (selectedSource === 'plex') {
        var plexUrl = document.getElementById('plex_url').value;
        var plexToken = document.getElementById('plex_token').value;
        if (!plexUrl || !plexToken) {
            alert('Please provide Plex URL and Token before scanning.');
            return;
        }
    }

    // Submit the scan form
    document.getElementById('scanForm').submit();
}

// File browser functionality
let currentTargetField = null;
let currentPath = '/';
let currentFileType = 'directory';

function openFileBrowser(targetFieldId) {
    currentTargetField = targetFieldId;
    currentPath = '/';
    document.getElementById('currentPath').textContent = currentPath;
    
    // Set file type based on the target field
    currentFileType = targetFieldId === 'ffmpeg_path' ? 'file' : 'directory';
    
    // Update modal title based on what we're browsing for
    const modalTitle = document.getElementById('fileBrowserTitle');
    if (modalTitle) {
        if (currentFileType === 'file') {
            modalTitle.textContent = 'Select FFmpeg Executable';
        } else {
            modalTitle.textContent = 'Browse Directories';
        }
    }

    // Load the root directory
    loadDirectoryContents(currentPath);

    // Show the modal
    document.getElementById('fileBrowserModal').style.display = 'block';
}

function closeFileBrowser() {
    document.getElementById('fileBrowserModal').style.display = 'none';
}

function loadDirectoryContents(path) {
    // Make an AJAX request to get directory contents
    fetch(`/admin/browse?path=${encodeURIComponent(path)}&type=${currentFileType}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert(`Error: ${data.error}`);
                return;
            }

            const directoryList = document.getElementById('directoryList');
            directoryList.innerHTML = '';

            // Add parent directory option if not at root
            if (path !== '/') {
                const parentItem = document.createElement('div');
                parentItem.className = 'directory-item parent';
                parentItem.innerHTML = '<span class="directory-icon">📁</span> ..';
                parentItem.addEventListener('click', () => {
                    const parentPath = path.split('/').slice(0, -1).join('/') || '/';
                    navigateToDirectory(parentPath);
                });
                directoryList.appendChild(parentItem);
            }

            // Add directories
            data.directories.forEach(dir => {
                const dirItem = document.createElement('div');
                dirItem.className = 'directory-item';
                dirItem.innerHTML = `<span class="directory-icon">📁</span> ${dir}`;
                dirItem.addEventListener('click', () => {
                    const newPath = path === '/' ? `/${dir}` : `${path}/${dir}`;
                    navigateToDirectory(newPath);
                });
                directoryList.appendChild(dirItem);
            });
            
            // Add files (only for ffmpeg selection)
            if (data.files && currentFileType === 'file') {
                data.files.forEach(file => {
                    const fileItem = document.createElement('div');
                    fileItem.className = 'directory-item file-item';
                    fileItem.innerHTML = `<span class="file-icon">⚙️</span> ${file}`;
                    fileItem.addEventListener('click', () => {
                        selectFile(path, file);
                    });
                    directoryList.appendChild(fileItem);
                });
            }
        })
        .catch(error => {
            console.error('Error fetching directory contents:', error);
            alert('Failed to load directory contents. See console for details.');
        });
}

function navigateToDirectory(path) {
    currentPath = path;
    document.getElementById('currentPath').textContent = currentPath;
    loadDirectoryContents(path);
}

function selectFile(path, filename) {
    const fullPath = path === '/' ? `/${filename}` : `${path}/${filename}`;
    const targetField = document.getElementById(currentTargetField);
    targetField.value = fullPath;
    closeFileBrowser();
}

function selectCurrentPath() {
    const targetField = document.getElementById(currentTargetField);
    // Only select the current path if we're browsing for directories
    if (currentFileType === 'directory') {
        targetField.value = currentPath;
        closeFileBrowser();
    } else {
        // For files, show a message that they need to select a file
        alert('Please select an FFmpeg executable file.');
    }
}

// Load and display libraries
function loadLibraries() {
    const libraryList = document.getElementById('libraryList');
    libraryList.innerHTML = '<p class="loading">Loading available libraries...</p>';
    
    fetch('/admin/api/libraries')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                libraryList.innerHTML = `<p class="error">Error loading libraries: ${data.error}</p>`;
                return;
            }
            
            if (!data.libraries || data.libraries.length === 0) {
                libraryList.innerHTML = '<p>No libraries found. Please configure your media server and ensure it has libraries.</p>';
                return;
            }
            
            // Create the library toggle UI
            const movieLibraries = data.libraries.filter(lib => lib.type === 'movie');
            const tvLibraries = data.libraries.filter(lib => lib.type === 'show');
            const otherLibraries = data.libraries.filter(lib => lib.type !== 'movie' && lib.type !== 'show');
            
            let html = '';
            
            // Movies section
            if (movieLibraries.length > 0) {
                html += '<h3>Movie Libraries</h3>';
                html += '<div class="library-group">';
                movieLibraries.forEach(lib => {
                    html += createLibraryToggle(lib);
                });
                html += '</div>';
            }
            
            // TV Shows section
            if (tvLibraries.length > 0) {
                html += '<h3>TV Show Libraries</h3>';
                html += '<div class="library-group">';
                tvLibraries.forEach(lib => {
                    html += createLibraryToggle(lib);
                });
                html += '</div>';
            }
            
            // Other Libraries section
            if (otherLibraries.length > 0) {
                html += '<h3>Other Libraries</h3>';
                html += '<div class="library-group">';
                otherLibraries.forEach(lib => {
                    html += createLibraryToggle(lib);
                });
                html += '</div>';
            }
            
            libraryList.innerHTML = html;
        })
        .catch(error => {
            libraryList.innerHTML = `<p class="error">Error: ${error.message}</p>`;
        });
}

function createLibraryToggle(library) {
    return `
        <div class="library-item">
            <label class="toggle-switch">
                <input type="checkbox" class="library-toggle-checkbox" 
                       name="enabled_libraries[]" 
                       value="${library.id}" 
                       ${library.enabled ? 'checked' : ''}>
                <span class="toggle-slider"></span>
                <span class="toggle-label">${library.title}</span>
                <small class="library-type">${library.type}</small>
            </label>
        </div>
    `;
}

// Add bulk action functions for toggling all checkboxes
function toggleAllLibraries(targetState) {
    document.querySelectorAll('.library-toggle-checkbox').forEach(checkbox => {
        checkbox.checked = targetState;
    });
}

// Function to renumber the mappings after removal
function renumberMappings() {
    const pathMappingsContainer = document.getElementById('pathMappings');
    const mappingRows = pathMappingsContainer.querySelectorAll('.path-mapping-row');
    
    // Skip the first row (which uses source_path and target_path without numbers)
    for (let i = 1; i < mappingRows.length; i++) {
        const row = mappingRows[i];
        const sourceInput = row.querySelector('input[name^="source_path_"]');
        const targetInput = row.querySelector('input[name^="target_path_"]');
        const sourceLabel = row.querySelector('label[for^="source_path_"]');
        const targetLabel = row.querySelector('label[for^="target_path_"]');
        
        if (sourceInput && targetInput) {
            // Update the input IDs and names
            sourceInput.id = `source_path_${i}`;
            sourceInput.name = `source_path_${i}`;
            targetInput.id = `target_path_${i}`;
            targetInput.name = `target_path_${i}`;
            
            // Update the labels
            if (sourceLabel) {
                sourceLabel.setAttribute('for', `source_path_${i}`);
                sourceLabel.textContent = `Media Server Path ${i + 1}`;
            }
            if (targetLabel) {
                targetLabel.setAttribute('for', `target_path_${i}`);
                targetLabel.textContent = `Squishy Path ${i + 1}`;
            }
        }
    }
}

function detectHardwareAcceleration() {
    // Show loading message
    const hwaccelResults = document.getElementById('hwaccel-results');
    const methodsDiv = document.getElementById('hwaccel-methods');
    const devicesDiv = document.getElementById('hwaccel-devices');
    
    methodsDiv.innerHTML = '<p>Detecting hardware acceleration methods. This may take a few moments...</p>';
    hwaccelResults.style.display = 'block';
    
    // Make API request to detect hardware acceleration
    fetch('/admin/detect_hw_accel')
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            // Display results
            displayHardwareAccelerationResults(data);
        })
        .catch(error => {
            methodsDiv.innerHTML = `<p class="error">Error detecting hardware acceleration: ${error.message}</p>`;
        });
}

function displayHardwareAccelerationResults(data) {
    const methodsDiv = document.getElementById('hwaccel-methods');
    const devicesDiv = document.getElementById('hwaccel-devices');
    const hwAccelSelect = document.getElementById('hw_accel');
    const hwDeviceInput = document.getElementById('hw_device');
    
    // Clear previous results
    methodsDiv.innerHTML = '';
    devicesDiv.innerHTML = '';
    
    // Methods
    if (data.methods && data.methods.length > 0) {
        const methodsList = document.createElement('ul');
        data.methods.forEach(method => {
            const li = document.createElement('li');
            
            // Create method entry with apply button
            const methodSpan = document.createElement('span');
            methodSpan.textContent = method;
            li.appendChild(methodSpan);
            
            // Only add apply button for usable HW acceleration methods
            if (['nvenc', 'cuda', 'qsv', 'vaapi', 'videotoolbox', 'amf'].includes(method)) {
                const applyButton = document.createElement('button');
                applyButton.textContent = 'Use';
                applyButton.className = 'button small';
                applyButton.style.marginLeft = '10px';
                applyButton.addEventListener('click', function() {
                    // Set the hardware acceleration method
                    hwAccelSelect.value = method;
                    
                    // Trigger change event to update device field visibility
                    const event = new Event('change');
                    hwAccelSelect.dispatchEvent(event);
                });
                li.appendChild(applyButton);
            }
            
            methodsList.appendChild(li);
        });
        methodsDiv.appendChild(methodsList);
    } else {
        methodsDiv.innerHTML = '<p>No hardware acceleration methods detected.</p>';
    }
    
    // Devices
    let hasDevices = false;
    
    if (data.devices) {
        for (const [type, devices] of Object.entries(data.devices)) {
            if (devices.length > 0) {
                hasDevices = true;
                
                const deviceHeader = document.createElement('h4');
                deviceHeader.textContent = type.toUpperCase();
                devicesDiv.appendChild(deviceHeader);
                
                const devicesList = document.createElement('ul');
                devices.forEach(device => {
                    const li = document.createElement('li');
                    
                    // Display device info with apply button
                    let deviceText = '';
                    let deviceValue = '';
                    
                    if (device.name && device.index) {
                        deviceText = `${device.name} (${device.index})`;
                        deviceValue = device.index;
                    } else if (device.path) {
                        deviceText = device.path;
                        deviceValue = device.path;
                    } else {
                        deviceText = JSON.stringify(device);
                    }
                    
                    const deviceSpan = document.createElement('span');
                    deviceSpan.textContent = deviceText;
                    li.appendChild(deviceSpan);
                    
                    // Add apply button for devices that match the acceleration type
                    if ((type === 'cuda' && hwAccelSelect.value === 'nvenc') || 
                        (type === hwAccelSelect.value)) {
                        const applyButton = document.createElement('button');
                        applyButton.textContent = 'Use';
                        applyButton.className = 'button small';
                        applyButton.style.marginLeft = '10px';
                        applyButton.addEventListener('click', function() {
                            // Set the device value
                            hwDeviceInput.value = deviceValue;
                        });
                        li.appendChild(applyButton);
                    }
                    
                    devicesList.appendChild(li);
                });
                devicesDiv.appendChild(devicesList);
            }
        }
    }
    
    if (!hasDevices) {
        devicesDiv.innerHTML = '<p>No hardware acceleration devices detected.</p>';
    }
    
    // Add Apply All button if methods were detected
    if (data.methods && data.methods.length > 0) {
        const applyContainer = document.createElement('div');
        applyContainer.style.marginTop = '20px';
        applyContainer.style.textAlign = 'right';
        
        let recommendedMethod = '';
        let recommendedDevice = '';
        
        // Determine best method to use
        if (data.methods.includes('nvenc')) {
            recommendedMethod = 'nvenc';
            if (data.devices.cuda && data.devices.cuda.length > 0) {
                recommendedDevice = data.devices.cuda[0].index || '0';
            }
        } else if (data.methods.includes('qsv')) {
            recommendedMethod = 'qsv';
        } else if (data.methods.includes('vaapi')) {
            recommendedMethod = 'vaapi';
            if (data.devices.vaapi && data.devices.vaapi.length > 0) {
                recommendedDevice = data.devices.vaapi[0].path;
            }
        } else if (data.methods.includes('videotoolbox')) {
            recommendedMethod = 'videotoolbox';
        } else if (data.methods.includes('amf')) {
            recommendedMethod = 'amf';
        }
        
        if (recommendedMethod) {
            const applyButton = document.createElement('button');
            applyButton.textContent = 'Apply Recommended Settings';
            applyButton.className = 'button';
            applyButton.addEventListener('click', function() {
                // Set the hardware acceleration method
                hwAccelSelect.value = recommendedMethod;
                
                // Set device if applicable
                if (recommendedDevice) {
                    hwDeviceInput.value = recommendedDevice;
                }
                
                // Trigger change event to update device field visibility
                const event = new Event('change');
                hwAccelSelect.dispatchEvent(event);
            });
            applyContainer.appendChild(applyButton);
            devicesDiv.appendChild(applyContainer);
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    toggleSourceFields();
    
    // Load libraries
    loadLibraries();
    
    // Add refresh button handler
    const refreshButton = document.getElementById('refreshLibrariesBtn');
    if (refreshButton) {
        refreshButton.addEventListener('click', loadLibraries);
    }
    
    // Add bulk action handlers
    const toggleAllButton = document.getElementById('toggleAllLibrariesBtn');
    if (toggleAllButton) {
        toggleAllButton.addEventListener('click', function() {
            const checkboxes = document.querySelectorAll('.library-toggle-checkbox');
            const anyChecked = Array.from(checkboxes).some(cb => cb.checked);
            const anyUnchecked = Array.from(checkboxes).some(cb => !cb.checked);
            
            // If all are checked, uncheck all; if some or none are checked, check all
            const newState = !(anyChecked && !anyUnchecked);
            
            // Toggle all checkboxes to the new state
            toggleAllLibraries(newState);
        });
    }
    
    const enableAllButton = document.getElementById('enableAllLibrariesBtn');
    if (enableAllButton) {
        enableAllButton.addEventListener('click', function() {
            toggleAllLibraries(true);
        });
    }
    
    const disableAllButton = document.getElementById('disableAllLibrariesBtn');
    if (disableAllButton) {
        disableAllButton.addEventListener('click', function() {
            toggleAllLibraries(false);
        });
    }
    
    // Set up hardware acceleration UI interactions
    const hwAccelSelect = document.getElementById('hw_accel');
    if (hwAccelSelect) {
        hwAccelSelect.addEventListener('change', toggleHwDeviceField);
    }
    
    // Set up hardware acceleration detection
    const detectHwAccelButton = document.querySelector('a[href="/admin/detect_hw_accel"]');
    if (detectHwAccelButton) {
        detectHwAccelButton.addEventListener('click', function(e) {
            e.preventDefault();
            detectHardwareAcceleration();
        });
    }
    
    // Path mapping UI functionality
    const addMappingButton = document.getElementById('addMapping');
    if (addMappingButton) {
        addMappingButton.addEventListener('click', function() {
            const pathMappingsContainer = document.getElementById('pathMappings');
            const existingMappings = pathMappingsContainer.querySelectorAll('.path-mapping-row');
            const nextIndex = existingMappings.length;
            
            const newMapping = document.createElement('div');
            newMapping.className = 'path-mapping-row';
            newMapping.innerHTML = `
                <div class="form-group">
                    <label for="source_path_${nextIndex}">Media Server Path ${nextIndex + 1}</label>
                    <div class="input-with-button">
                        <input type="text" id="source_path_${nextIndex}" name="source_path_${nextIndex}" placeholder="/another/path">
                        <button type="button" class="remove-mapping button danger small">Remove</button>
                    </div>
                </div>
                <div class="form-group">
                    <label for="target_path_${nextIndex}">Squishy Path ${nextIndex + 1}</label>
                    <input type="text" id="target_path_${nextIndex}" name="target_path_${nextIndex}" placeholder="/local/path">
                </div>
            `;
            
            pathMappingsContainer.appendChild(newMapping);
            
            // Add click handler for the remove button
            const removeButton = newMapping.querySelector('.remove-mapping');
            if (removeButton) {
                removeButton.addEventListener('click', function() {
                    newMapping.remove();
                    // Re-number the remaining mappings
                    renumberMappings();
                });
            }
        });
    }
    
    // Add click handlers for existing remove buttons
    document.querySelectorAll('.remove-mapping').forEach(button => {
        button.addEventListener('click', function() {
            const mappingRow = this.closest('.path-mapping-row');
            if (mappingRow) {
                mappingRow.remove();
                renumberMappings();
            }
        });
    });
});