function toggleSourceFields() {
    // Hide all source fields first
    document.querySelectorAll('.source-fields').forEach(function(el) {
        el.style.display = 'none';
    });

    // Get the selected source
    var selectedRadio = document.querySelector('input[name="source"]:checked');
    
    // If no radio is checked (fresh install), default to jellyfin
    var selectedSource = selectedRadio ? selectedRadio.value : 'jellyfin';
    
    // If no radio is checked, check the jellyfin radio
    if (!selectedRadio) {
        var jellyfinRadio = document.querySelector('input[name="source"][value="jellyfin"]');
        if (jellyfinRadio) {
            jellyfinRadio.checked = true;
        }
    }
    
    // Show the selected source fields
    var fieldsElement = document.getElementById(selectedSource + 'Fields');
    if (fieldsElement) {
        fieldsElement.style.display = 'block';
    }

    // Update the scan type in the hidden form
    var scanTypeElement = document.getElementById('scan_type');
    if (scanTypeElement) {
        scanTypeElement.value = selectedSource;
    }
}

// Hardware acceleration is now handled via capabilities JSON

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
    fetch(`/admin/browse_filesystem?path=${encodeURIComponent(path)}&type=${currentFileType}`)
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
    
    // If no mapping rows, we don't need to do anything
    if (mappingRows.length === 0) {
        return;
    }
    
    // Renumber all mapping rows
    for (let i = 0; i < mappingRows.length; i++) {
        const row = mappingRows[i];
        const sourceInput = row.querySelector('input[name^="source_path"]');
        const targetInput = row.querySelector('input[name^="target_path"]');
        const sourceLabel = row.querySelector('label[for^="source_path"]');
        const targetLabel = row.querySelector('label[for^="target_path"]');
        
        if (sourceInput && targetInput) {
            // Update the input IDs and names
            sourceInput.id = `source_path_${i}`;
            sourceInput.name = `source_path_${i}`;
            targetInput.id = `target_path_${i}`;
            targetInput.name = `target_path_${i}`;
            
            // Update the labels - first row doesn't have a number
            if (sourceLabel) {
                sourceLabel.setAttribute('for', `source_path_${i}`);
                if (i === 0) {
                    sourceLabel.textContent = `Media Server Path`;
                } else {
                    sourceLabel.textContent = `Media Server Path ${i + 1}`;
                }
            }
            if (targetLabel) {
                targetLabel.setAttribute('for', `target_path_${i}`);
                if (i === 0) {
                    targetLabel.textContent = `Squishy Path`;
                } else {
                    targetLabel.textContent = `Squishy Path ${i + 1}`;
                }
            }
        }
    }
}

function detectHardwareAcceleration() {
    // Show loading message
    const hwaccelResults = document.getElementById('hwaccel-results');
    hwaccelResults.innerHTML = '<p>Detecting hardware acceleration capabilities. This may take a few moments...</p>';
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
            hwaccelResults.innerHTML = `<p class="error">Error detecting hardware acceleration: ${error.message}</p>`;
        });
}

// Function to set up the edit/save capabilities functionality
function setupCapabilitiesEditing() {
    const editCapabilitiesButton = document.getElementById('edit-capabilities-button');
    const saveCapabilitiesButton = document.getElementById('save-capabilities-button');
    const capabilitiesTextArea = document.getElementById('capabilities-json-content');
    
    if (editCapabilitiesButton && saveCapabilitiesButton && capabilitiesTextArea) {
        // Edit button handler
        editCapabilitiesButton.addEventListener('click', function() {
            if (capabilitiesTextArea.readOnly) {
                // Enable editing
                capabilitiesTextArea.readOnly = false;
                editCapabilitiesButton.textContent = 'Disable Editing';
                capabilitiesTextArea.style.border = '2px solid #e74c3c';
                capabilitiesTextArea.style.backgroundColor = '#fff9f9';
                saveCapabilitiesButton.style.display = 'inline-block';
            } else {
                // Disable editing
                capabilitiesTextArea.readOnly = true;
                editCapabilitiesButton.textContent = 'Enable Editing';
                capabilitiesTextArea.style.border = '';
                capabilitiesTextArea.style.backgroundColor = '';
                saveCapabilitiesButton.style.display = 'none';
            }
        });
        
        // Save button handler
        saveCapabilitiesButton.addEventListener('click', function() {
            try {
                // Parse the JSON from the textarea
                const capabilities = JSON.parse(capabilitiesTextArea.value);
                
                // Validate the capabilities JSON
                if (!capabilities || typeof capabilities !== 'object') {
                    alert('Invalid JSON: Must be an object');
                    return;
                }
                
                // Check for required fields
                const requiredFields = ['hwaccel', 'device', 'encoders', 'fallback_encoders'];
                for (const field of requiredFields) {
                    if (!(field in capabilities)) {
                        alert(`Missing required field: ${field}`);
                        return;
                    }
                }
                
                // Make API request to save capabilities
                fetch('/admin/save_hw_capabilities', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ capabilities: capabilities }),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('Hardware capabilities saved successfully!');
                        
                        // Update the textarea with the saved capabilities
                        if (data.capabilities) {
                            capabilitiesTextArea.value = JSON.stringify(data.capabilities, null, 2);
                        }
                        
                        // Reset UI
                        capabilitiesTextArea.readOnly = true;
                        editCapabilitiesButton.textContent = 'Enable Editing';
                        capabilitiesTextArea.style.border = '';
                        capabilitiesTextArea.style.backgroundColor = '';
                        saveCapabilitiesButton.style.display = 'none';
                    } else {
                        alert('Error saving capabilities: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    alert('Error saving capabilities: ' + error.message);
                });
            } catch (e) {
                alert('Invalid JSON syntax: ' + e.message);
            }
        });
    }
}

function displayHardwareAccelerationResults(data) {
    const hwaccelResults = document.getElementById('hwaccel-results');
    
    // Clear previous results
    hwaccelResults.innerHTML = '';
    hwaccelResults.style.display = 'block';
    
    // We don't need to do anything with stored capabilities here
    // as they are already displayed in the template
    
    // Create a summary section for detected methods
    const summarySection = document.createElement('div');
    summarySection.className = 'hw-summary-section';
    
    const summaryHeader = document.createElement('h3');
    summaryHeader.textContent = 'Detection Summary';
    summarySection.appendChild(summaryHeader);
    
    // Add detected methods
    const methodsHeader = document.createElement('h4');
    methodsHeader.textContent = 'Available Hardware Acceleration Methods:';
    summarySection.appendChild(methodsHeader);
    
    if (data.methods && data.methods.length > 0) {
        const methodsList = document.createElement('ul');
        data.methods.forEach(method => {
            const li = document.createElement('li');
            li.textContent = method;
            methodsList.appendChild(li);
        });
        summarySection.appendChild(methodsList);
    } else {
        const noMethodsMsg = document.createElement('p');
        noMethodsMsg.textContent = 'No hardware acceleration methods detected.';
        summarySection.appendChild(noMethodsMsg);
    }
    
    // Add recommended method if available
    if (data.recommended && data.recommended.method) {
        const recommendedDiv = document.createElement('div');
        recommendedDiv.className = 'recommended-hw';
        
        const recommendedHeader = document.createElement('h4');
        recommendedHeader.textContent = 'Recommended Configuration:';
        recommendedDiv.appendChild(recommendedHeader);
        
        const recommendedInfo = document.createElement('p');
        recommendedInfo.innerHTML = `<strong>Method:</strong> ${data.recommended.method}`;
        if (data.recommended.device) {
            recommendedInfo.innerHTML += `<br><strong>Device:</strong> ${data.recommended.device}`;
        }
        recommendedDiv.appendChild(recommendedInfo);
        
        summarySection.appendChild(recommendedDiv);
    }
    
    hwaccelResults.appendChild(summarySection);
    
    // Display raw capabilities JSON
    if (data.capabilities_json) {
        // Add a save button to store the newly detected capabilities
        const saveDetectedContainer = document.createElement('div');
        saveDetectedContainer.className = 'save-detected-container';
        saveDetectedContainer.style.marginTop = '20px';
        saveDetectedContainer.style.marginBottom = '20px';
        
        const saveDetectedButton = document.createElement('button');
        saveDetectedButton.textContent = 'Save Detected Capabilities';
        saveDetectedButton.className = 'button success';
        saveDetectedButton.addEventListener('click', function() {
            try {
                // Make API request to save capabilities
                fetch('/admin/save_hw_capabilities', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ capabilities: data.capabilities_json }),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('Hardware capabilities saved successfully!');
                        
                        // Instead of reloading the page, update the UI
                        // Create or update the capabilities display in the existing UI
                        const existingCapabilities = document.querySelector('.capabilities-json');
                        
                        if (existingCapabilities) {
                            // Update existing capabilities display
                            const capabilitiesTextArea = document.getElementById('capabilities-json-content');
                            if (capabilitiesTextArea && data.capabilities) {
                                capabilitiesTextArea.value = JSON.stringify(data.capabilities, null, 2);
                            }
                        } else {
                            // Create new capabilities display
                            const capabilitiesSection = document.createElement('div');
                            capabilitiesSection.className = 'capabilities-json';
                            
                            const capabilitiesHeader = document.createElement('h3');
                            capabilitiesHeader.textContent = 'Current Hardware Capabilities';
                            capabilitiesSection.appendChild(capabilitiesHeader);
                            
                            const capabilitiesDescription = document.createElement('p');
                            capabilitiesDescription.className = 'help-text';
                            capabilitiesDescription.innerHTML = 'These hardware acceleration capabilities are currently configured in Squishy. <strong>Advanced users only:</strong> You can edit this configuration if you need to make manual adjustments.';
                            capabilitiesSection.appendChild(capabilitiesDescription);
                            
                            const capabilitiesTextArea = document.createElement('textarea');
                            capabilitiesTextArea.id = 'capabilities-json-content';
                            capabilitiesTextArea.value = JSON.stringify(data.capabilities, null, 2);
                            capabilitiesTextArea.readOnly = true;
                            capabilitiesTextArea.rows = 12;
                            capabilitiesTextArea.style.width = '100%';
                            capabilitiesTextArea.style.fontFamily = 'monospace';
                            capabilitiesTextArea.style.fontSize = '0.9rem';
                            capabilitiesSection.appendChild(capabilitiesTextArea);
                            
                            const actionsDiv = document.createElement('div');
                            actionsDiv.className = 'capabilities-actions';
                            actionsDiv.style.marginTop = '15px';
                            
                            const editButton = document.createElement('button');
                            editButton.id = 'edit-capabilities-button';
                            editButton.className = 'button';
                            editButton.textContent = 'Enable Editing';
                            actionsDiv.appendChild(editButton);
                            
                            const saveButton = document.createElement('button');
                            saveButton.id = 'save-capabilities-button';
                            saveButton.className = 'button success';
                            saveButton.style.marginLeft = '10px';
                            saveButton.style.display = 'none';
                            saveButton.textContent = 'Save Capabilities';
                            actionsDiv.appendChild(saveButton);
                            
                            capabilitiesSection.appendChild(actionsDiv);
                            
                            // Replace the save button container with the capabilities section
                            saveDetectedContainer.replaceWith(capabilitiesSection);
                            
                            // Remove other detection results
                            const detectedCapabilitiesContainer = document.querySelector('.capabilities-json:not(:first-child)');
                            if (detectedCapabilitiesContainer) {
                                detectedCapabilitiesContainer.remove();
                            }
                            
                            // Set up the edit/save functionality
                            setupCapabilitiesEditing();
                        }
                    } else {
                        alert('Error saving capabilities: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    alert('Error saving capabilities: ' + error.message);
                });
            } catch (e) {
                alert('Error: ' + e.message);
            }
        });
        saveDetectedContainer.appendChild(saveDetectedButton);
        hwaccelResults.appendChild(saveDetectedContainer);
        
        // Display the detected capabilities
        const capabilitiesContainer = document.createElement('div');
        capabilitiesContainer.className = 'capabilities-json';
        
        const capabilitiesHeader = document.createElement('h3');
        capabilitiesHeader.textContent = 'Detected Hardware Capabilities';
        capabilitiesContainer.appendChild(capabilitiesHeader);
        
        const capabilitiesDescription = document.createElement('p');
        capabilitiesDescription.className = 'help-text';
        capabilitiesDescription.innerHTML = 'This JSON file defines all hardware acceleration capabilities detected on your system. Click "Save Detected Capabilities" above to use this configuration.';
        capabilitiesContainer.appendChild(capabilitiesDescription);
        
        const capabilitiesTextArea = document.createElement('textarea');
        capabilitiesTextArea.id = 'detected-capabilities-json';
        capabilitiesTextArea.value = JSON.stringify(data.capabilities_json, null, 2);
        capabilitiesTextArea.readOnly = true;
        capabilitiesTextArea.rows = 12;
        capabilitiesTextArea.style.width = '100%';
        capabilitiesTextArea.style.fontFamily = 'monospace';
        capabilitiesTextArea.style.fontSize = '0.9rem';
        capabilitiesContainer.appendChild(capabilitiesTextArea);
        
        hwaccelResults.appendChild(capabilitiesContainer);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // For a fresh install, we need to make sure one of the source fields is shown
    const sourceRadios = document.querySelectorAll('input[name="source"]');
    if (sourceRadios.length > 0) {
        // If none is checked, check the first one by default (jellyfin)
        const anyChecked = Array.from(sourceRadios).some(radio => radio.checked);
        if (!anyChecked && sourceRadios[0]) {
            sourceRadios[0].checked = true;
        }
        toggleSourceFields();
    }
    
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
    
    // Hardware acceleration is now handled via capabilities JSON
    
    // Set up hardware acceleration detection
    const detectHwAccelButton = document.querySelector('a[href="/admin/detect_hw_accel"]');
    if (detectHwAccelButton) {
        detectHwAccelButton.addEventListener('click', function(e) {
            e.preventDefault();
            detectHardwareAcceleration();
        });
    }
    
    // Set up existing capabilities editing
    setupCapabilitiesEditing();
    
    // Path mapping UI functionality
    const addMappingButton = document.getElementById('addMapping');
    if (addMappingButton) {
        addMappingButton.addEventListener('click', function() {
            const pathMappingsContainer = document.getElementById('pathMappings');
            
            // Remove empty state message if it exists
            const emptyState = pathMappingsContainer.querySelector('.path-mapping-empty');
            if (emptyState) {
                emptyState.remove();
            }
            
            const existingMappings = pathMappingsContainer.querySelectorAll('.path-mapping-row');
            const nextIndex = existingMappings.length;
            
            const newMapping = document.createElement('div');
            newMapping.className = 'path-mapping-row';
            
            // If this is the first mapping (index 0), don't include a number in the label
            const labelNumber = nextIndex === 0 ? '' : ` ${nextIndex + 1}`;
            
            newMapping.innerHTML = `
                <div class="mapping-fields">
                    <div class="form-group">
                        <label for="source_path_${nextIndex}">Media Server Path${labelNumber}</label>
                        <input type="text" id="source_path_${nextIndex}" name="source_path_${nextIndex}" placeholder="/media">
                    </div>
                    <div class="form-group">
                        <label for="target_path_${nextIndex}">Squishy Path${labelNumber}</label>
                        <input type="text" id="target_path_${nextIndex}" name="target_path_${nextIndex}" placeholder="/opt/media">
                    </div>
                </div>
                <div class="mapping-actions">
                    <button type="button" class="remove-mapping circle-button cancel-button" data-tooltip="Remove">
                        <img src="/static/img/cancel.svg" alt="Remove" width="24" height="24">
                    </button>
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
                    
                    // If no mappings left, show the empty state message
                    if (pathMappingsContainer.querySelectorAll('.path-mapping-row').length === 0) {
                        const emptyStateDiv = document.createElement('div');
                        emptyStateDiv.className = 'path-mapping-empty';
                        emptyStateDiv.innerHTML = '<p>No path mappings configured. Click "Add Mapping" below to create your first mapping.</p>';
                        pathMappingsContainer.appendChild(emptyStateDiv);
                    }
                });
            }
        });
    }
    
    // Add click handlers for existing remove buttons
    document.querySelectorAll('.remove-mapping').forEach(button => {
        button.addEventListener('click', function() {
            const mappingRow = this.closest('.path-mapping-row');
            const pathMappingsContainer = document.getElementById('pathMappings');
            
            if (mappingRow) {
                mappingRow.remove();
                renumberMappings();
                
                // If no mappings left, show the empty state message
                if (pathMappingsContainer.querySelectorAll('.path-mapping-row').length === 0) {
                    const emptyStateDiv = document.createElement('div');
                    emptyStateDiv.className = 'path-mapping-empty';
                    emptyStateDiv.innerHTML = '<p>No path mappings configured. Click "Add Mapping" below to create your first mapping.</p>';
                    pathMappingsContainer.appendChild(emptyStateDiv);
                }
            }
        });
    });
});