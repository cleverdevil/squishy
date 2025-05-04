/**
 * Onboarding functionality for Squishy
 * 
 * Handles the onboarding wizard functionality across the various steps
 */

document.addEventListener('DOMContentLoaded', function() {
    // Common functions used throughout the onboarding process
    
    // Step 1: Media Source Configuration
    initMediaSourceStep();
    
    // Step 2: Media Libraries
    initMediaLibrariesStep();
    
    // Step 3: Path Configuration
    initPathConfigurationStep();
    
    // Step 4: Library Scan
    initLibraryScanStep();
    
    // Step 5: Transcoding Presets
    initPresetSelectionStep();
    
    // Step 6: Hardware Acceleration
    initHardwareAccelerationStep();
});

/**
 * Step 1: Media Source Configuration
 */
function initMediaSourceStep() {
    // Source selection toggle
    const toggleSourceFields = function() {
        const jellyfinRadio = document.querySelector('input[name="source"][value="jellyfin"]');
        const jellyfinFields = document.getElementById('jellyfinFields');
        const plexFields = document.getElementById('plexFields');
        
        if (jellyfinRadio && jellyfinFields && plexFields) {
            if (jellyfinRadio.checked) {
                jellyfinFields.style.display = 'block';
                plexFields.style.display = 'none';
            } else {
                jellyfinFields.style.display = 'none';
                plexFields.style.display = 'block';
            }
        }
    };
    
    // Apply source selection handling
    const sourceRadios = document.querySelectorAll('input[name="source"]');
    if (sourceRadios) {
        sourceRadios.forEach(radio => {
            radio.addEventListener('change', toggleSourceFields);
        });
    }
    
    // Highlight selected radio card
    const radioCards = document.querySelectorAll('.radio-card');
    if (radioCards) {
        radioCards.forEach(card => {
            const radio = card.querySelector('input[type="radio"]');
            if (radio) {
                radio.addEventListener('change', function() {
                    // Remove selected class from all cards
                    radioCards.forEach(c => c.classList.remove('selected'));
                    
                    // Add selected class to this card if radio is checked
                    if (this.checked) {
                        card.classList.add('selected');
                    }
                });
            }
        });
    }
    
    // Make toggleSourceFields function available globally for the page
    window.toggleSourceFields = toggleSourceFields;
}

/**
 * Step 2: Media Libraries
 */
function initMediaLibrariesStep() {
    // Library selection step
    const libraryForm = document.getElementById('libraryForm');
    const libraryList = document.getElementById('libraryList');
    const noLibrariesWarning = document.querySelector('.no-libraries-warning');
    
    if (libraryList) {
        // Load libraries from the server
        fetch('/onboarding/get_libraries')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.libraries && data.libraries.length > 0) {
                    // Hide loading
                    libraryList.innerHTML = '';
                    
                    // Create library checkbox list
                    const enabledLibraries = data.enabled_libraries || {};
                    
                    data.libraries.forEach(library => {
                        const isEnabled = enabledLibraries[library.id] !== false; // Default to enabled
                        
                        const libraryRow = document.createElement('div');
                        libraryRow.className = 'library-item';
                        
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.id = `library_${library.id}`;
                        checkbox.name = `library_${library.id}`;
                        checkbox.checked = isEnabled;
                        
                        const label = document.createElement('label');
                        label.htmlFor = `library_${library.id}`;
                        label.textContent = library.name;
                        
                        libraryRow.appendChild(checkbox);
                        libraryRow.appendChild(label);
                        libraryList.appendChild(libraryRow);
                    });
                } else {
                    // Show warning if no libraries found
                    if (noLibrariesWarning) {
                        noLibrariesWarning.style.display = 'block';
                    }
                    
                    // Clear library list
                    libraryList.innerHTML = '<p>No libraries found on your media server.</p>';
                }
            })
            .catch(error => {
                console.error('Error loading libraries:', error);
                
                // Show error message
                libraryList.innerHTML = '<p>Error loading libraries. Please check your media server connection.</p>';
            });
        
        // Toggle all libraries buttons
        const toggleAllBtn = document.getElementById('toggleAllLibrariesBtn');
        const enableAllBtn = document.getElementById('enableAllLibrariesBtn');
        const disableAllBtn = document.getElementById('disableAllLibrariesBtn');
        
        if (toggleAllBtn) {
            toggleAllBtn.addEventListener('click', function() {
                const checkboxes = libraryList.querySelectorAll('input[type="checkbox"]');
                const allChecked = Array.from(checkboxes).every(cb => cb.checked);
                
                checkboxes.forEach(cb => {
                    cb.checked = !allChecked;
                });
            });
        }
        
        if (enableAllBtn) {
            enableAllBtn.addEventListener('click', function() {
                const checkboxes = libraryList.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = true;
                });
            });
        }
        
        if (disableAllBtn) {
            disableAllBtn.addEventListener('click', function() {
                const checkboxes = libraryList.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = false;
                });
            });
        }
    }
}

/**
 * Step 3: Path Configuration
 */
function initPathConfigurationStep() {
    // Path mapping functionality
    const pathMappings = document.getElementById('pathMappings');
    const addMappingBtn = document.getElementById('addMapping');
    
    if (addMappingBtn && pathMappings) {
        let mappingCount = pathMappings.querySelectorAll('.path-mapping-row').length;
        
        // Add a new mapping row
        addMappingBtn.addEventListener('click', function() {
            // Hide empty state message if it exists
            const emptyState = pathMappings.querySelector('.path-mapping-empty');
            if (emptyState) {
                emptyState.style.display = 'none';
            }
            
            // Create a new mapping row
            const newRow = document.createElement('div');
            newRow.className = 'path-mapping-row';
            
            newRow.innerHTML = `
                <div class="mapping-fields">
                    <div class="form-group">
                        <label for="source_path_${mappingCount}">Media Server Path ${mappingCount > 0 ? mappingCount + 1 : ''}</label>
                        <input type="text" id="source_path_${mappingCount}" name="source_path_${mappingCount}" placeholder="/media">
                    </div>
                    <div class="form-group">
                        <label for="target_path_${mappingCount}">Squishy Path ${mappingCount > 0 ? mappingCount + 1 : ''}</label>
                        <input type="text" id="target_path_${mappingCount}" name="target_path_${mappingCount}" placeholder="/opt/media">
                    </div>
                </div>
                <div class="mapping-actions">
                    <button type="button" class="remove-mapping circle-button cancel-button" data-tooltip="Remove">
                        <img src="/static/img/cancel.svg" alt="Remove" width="24" height="24">
                    </button>
                </div>
            `;
            
            pathMappings.appendChild(newRow);
            mappingCount++;
            
            // Add event listener to the new remove button
            const removeButton = newRow.querySelector('.remove-mapping');
            if (removeButton) {
                removeButton.addEventListener('click', function() {
                    newRow.remove();
                    
                    // If no mappings left, show empty state
                    if (pathMappings.querySelectorAll('.path-mapping-row').length === 0) {
                        if (emptyState) {
                            emptyState.style.display = 'block';
                        }
                    }
                });
            }
        });
        
        // Initialize existing remove buttons
        const removeButtons = pathMappings.querySelectorAll('.remove-mapping');
        removeButtons.forEach(button => {
            button.addEventListener('click', function() {
                const row = this.closest('.path-mapping-row');
                if (row) {
                    row.remove();
                    
                    // If no mappings left, show empty state
                    if (pathMappings.querySelectorAll('.path-mapping-row').length === 0) {
                        const emptyState = pathMappings.querySelector('.path-mapping-empty');
                        if (emptyState) {
                            emptyState.style.display = 'block';
                        } else {
                            const newEmptyState = document.createElement('div');
                            newEmptyState.className = 'path-mapping-empty';
                            newEmptyState.innerHTML = '<p>No path mappings configured. Click "Add Mapping" below to create your first mapping.</p>';
                            pathMappings.appendChild(newEmptyState);
                        }
                    }
                }
            });
        });
    }

    // File browser functionality
    const fileBrowserModal = document.getElementById('fileBrowserModal');
    const fileBrowserTitle = document.getElementById('fileBrowserTitle');
    const currentPathElement = document.getElementById('currentPath');
    const directoryList = document.getElementById('directoryList');
    let currentPath = '/';
    let targetInputId = null;

    // Function to open the file browser modal
    function openFileBrowser(inputId) {
        targetInputId = inputId;
        const inputElement = document.getElementById(inputId);
        
        // Set the title based on what we're browsing for
        if (fileBrowserTitle) {
            if (inputId === 'media_path') {
                fileBrowserTitle.textContent = 'Select Media Path';
            } else if (inputId === 'transcode_path') {
                fileBrowserTitle.textContent = 'Select Transcode Path';
            } else if (inputId === 'ffmpeg_path') {
                fileBrowserTitle.textContent = 'Select FFmpeg Path';
            } else if (inputId === 'ffprobe_path') {
                fileBrowserTitle.textContent = 'Select FFprobe Path';
            } else {
                fileBrowserTitle.textContent = 'Browse Directories';
            }
        }
        
        // Set the initial path
        currentPath = inputElement.value || '/';
        if (currentPathElement) {
            currentPathElement.textContent = currentPath;
        }
        
        // Load the directory contents
        loadDirectory(currentPath);
        
        // Show the modal
        if (fileBrowserModal) {
            fileBrowserModal.style.display = 'block';
        }
    }

    // Function to close the file browser modal
    function closeFileBrowser() {
        if (fileBrowserModal) {
            fileBrowserModal.style.display = 'none';
        }
    }

    // Function to load directory contents
    function loadDirectory(path) {
        if (directoryList) {
            // Show loading
            directoryList.innerHTML = '<div class="loading">Loading...</div>';
            
            // Fetch directory contents
            fetch(`/api/files?path=${encodeURIComponent(path)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Update current path
                        currentPath = path;
                        if (currentPathElement) {
                            currentPathElement.textContent = currentPath;
                        }
                        
                        // Clear directory list
                        directoryList.innerHTML = '';
                        
                        // Add parent directory if not at root
                        if (path !== '/') {
                            const parentDir = path.split('/').slice(0, -1).join('/') || '/';
                            const parentItem = document.createElement('div');
                            parentItem.className = 'directory-item parent';
                            parentItem.innerHTML = '<span class="directory-icon">../</span><span class="directory-name">Parent Directory</span>';
                            parentItem.addEventListener('click', function() {
                                loadDirectory(parentDir);
                            });
                            directoryList.appendChild(parentItem);
                        }
                        
                        // Add directories
                        if (data.directories && data.directories.length > 0) {
                            data.directories.forEach(dir => {
                                const dirItem = document.createElement('div');
                                dirItem.className = 'directory-item';
                                dirItem.innerHTML = `<span class="directory-icon">📁</span><span class="directory-name">${dir}</span>`;
                                dirItem.addEventListener('click', function() {
                                    const newPath = currentPath === '/' ? `/${dir}` : `${currentPath}/${dir}`;
                                    loadDirectory(newPath);
                                });
                                directoryList.appendChild(dirItem);
                            });
                        }
                        
                        // Add files if browsing for specific files
                        if (targetInputId === 'ffmpeg_path' || targetInputId === 'ffprobe_path') {
                            if (data.files && data.files.length > 0) {
                                data.files.forEach(file => {
                                    const fileItem = document.createElement('div');
                                    fileItem.className = 'directory-item file';
                                    fileItem.innerHTML = `<span class="directory-icon">📄</span><span class="directory-name">${file}</span>`;
                                    fileItem.addEventListener('click', function() {
                                        const filePath = currentPath === '/' ? `/${file}` : `${currentPath}/${file}`;
                                        selectPath(filePath);
                                    });
                                    directoryList.appendChild(fileItem);
                                });
                            }
                        }
                        
                        // Show message if empty
                        if (directoryList.children.length === 0) {
                            directoryList.innerHTML = '<div class="empty-directory">This directory is empty.</div>';
                        }
                    } else {
                        // Show error
                        directoryList.innerHTML = `<div class="directory-error">Error: ${data.message || 'Failed to load directory'}</div>`;
                    }
                })
                .catch(error => {
                    console.error('Error loading directory:', error);
                    directoryList.innerHTML = '<div class="directory-error">Error loading directory</div>';
                });
        }
    }

    // Function to select the current path
    function selectCurrentPath() {
        selectPath(currentPath);
    }

    // Function to select a path and close the browser
    function selectPath(path) {
        const inputElement = document.getElementById(targetInputId);
        if (inputElement) {
            inputElement.value = path;
        }
        closeFileBrowser();
    }

    // Add global functions for the file browser
    window.openFileBrowser = openFileBrowser;
    window.closeFileBrowser = closeFileBrowser;
    window.selectCurrentPath = selectCurrentPath;
}

/**
 * Step 4: Library Scan
 */
function initLibraryScanStep() {
    const startScanButton = document.getElementById('startScanButton');
    const skipScanButton = document.getElementById('skipScanButton');
    const scanStartSection = document.getElementById('scanStartSection');
    const scanProgressSection = document.getElementById('scanProgressSection');
    const scanResultsSection = document.getElementById('scanResultsSection');
    const scanSuccessSection = document.getElementById('scanSuccessSection');
    const scanErrorSection = document.getElementById('scanErrorSection');
    const continueAfterScanButton = document.getElementById('continueAfterScanButton');
    const skipScanForm = document.getElementById('skipScanForm');
    
    if (startScanButton && scanStartSection && scanProgressSection && scanResultsSection) {
        // Start scan button
        startScanButton.addEventListener('click', function() {
            // Show progress
            scanStartSection.style.display = 'none';
            scanProgressSection.style.display = 'block';
            
            // Disable skip button during scan
            if (skipScanButton) {
                skipScanButton.disabled = true;
            }
            
            // Start the scan
            fetch('/onboarding/scan_library', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Check scan status periodically until scan is complete
                        const checkScanStatus = function() {
                            fetch('/api/scan/status')
                                .then(response => response.json())
                                .then(status => {
                                    if (status.in_progress) {
                                        // Scan is still running, check again in 2 seconds
                                        setTimeout(checkScanStatus, 2000);
                                    } else {
                                        // Scan is complete, show results
                                        scanProgressSection.style.display = 'none';
                                        scanResultsSection.style.display = 'block';
                                        scanSuccessSection.style.display = 'block';
                                        scanErrorSection.style.display = 'none';
                                        
                                        // Update continue button
                                        if (continueAfterScanButton) {
                                            continueAfterScanButton.style.display = 'inline-block';
                                        }
                                        
                                        // Re-enable skip button
                                        if (skipScanButton) {
                                            skipScanButton.disabled = false;
                                            skipScanButton.style.display = 'none';
                                        }
                                        
                                        // Fetch scan stats if available
                                        fetch('/api/stats')
                                            .then(response => response.json())
                                            .then(statsData => {
                                                if (statsData.success) {
                                                    // Update stats in the UI
                                                    const movieCount = document.getElementById('movieCount');
                                                    const showCount = document.getElementById('showCount');
                                                    const episodeCount = document.getElementById('episodeCount');
                                                    
                                                    if (movieCount) movieCount.textContent = statsData.movies || 0;
                                                    if (showCount) showCount.textContent = statsData.shows || 0;
                                                    if (episodeCount) episodeCount.textContent = statsData.episodes || 0;
                                                }
                                            })
                                            .catch(error => {
                                                console.error('Error fetching stats:', error);
                                            });
                                    }
                                })
                                .catch(error => {
                                    console.error('Error checking scan status:', error);
                                    // If error, wait and try again
                                    setTimeout(checkScanStatus, 2000);
                                });
                        };
                        
                        // Start checking scan status
                        checkScanStatus();
                    } else {
                        // Show error message
                        scanProgressSection.style.display = 'none';
                        scanResultsSection.style.display = 'block';
                        scanSuccessSection.style.display = 'none';
                        scanErrorSection.style.display = 'block';
                        
                        // Re-enable skip button
                        if (skipScanButton) {
                            skipScanButton.disabled = false;
                        }
                    }
                })
                .catch(error => {
                    console.error('Error scanning library:', error);
                    
                    // Show error message
                    scanProgressSection.style.display = 'none';
                    scanResultsSection.style.display = 'block';
                    scanSuccessSection.style.display = 'none';
                    scanErrorSection.style.display = 'block';
                    
                    // Update error message
                    const scanErrorText = document.getElementById('scanErrorText');
                    if (scanErrorText) {
                        scanErrorText.textContent = 'An error occurred while scanning the library. Please try again or continue without scanning.';
                    }
                    
                    // Re-enable skip button
                    if (skipScanButton) {
                        skipScanButton.disabled = false;
                    }
                });
        });
        
        // Skip scan button
        if (skipScanButton && skipScanForm) {
            skipScanButton.addEventListener('click', function() {
                skipScanForm.submit();
            });
        }
        
        // Continue after scan button
        if (continueAfterScanButton) {
            continueAfterScanButton.addEventListener('click', function() {
                window.location.href = '/onboarding/step/5';
            });
        }
    }
}

/**
 * Step 5: Transcoding Presets
 */
function initPresetSelectionStep() {
    // Highlight the selected preset option
    const presetOptions = document.querySelectorAll('.preset-option');
    
    if (presetOptions) {
        presetOptions.forEach(option => {
            const radio = option.querySelector('input[type="radio"]');
            
            if (radio) {
                // Initial state
                if (radio.checked) {
                    option.classList.add('selected');
                }
                
                // Handle change
                radio.addEventListener('change', function() {
                    presetOptions.forEach(opt => {
                        opt.classList.remove('selected');
                    });
                    
                    if (this.checked) {
                        option.classList.add('selected');
                    }
                });
                
                // Click on the option should check the radio
                option.addEventListener('click', function(e) {
                    // Don't trigger if clicking on the radio itself
                    if (e.target !== radio) {
                        radio.checked = true;
                        
                        // Trigger change event
                        const event = new Event('change');
                        radio.dispatchEvent(event);
                    }
                });
            }
        });
    }
}

/**
 * Step 6: Hardware Acceleration
 */
function initHardwareAccelerationStep() {
    const detectHardwareBtn = document.getElementById('detectHardwareBtn');
    const detectionProgress = document.getElementById('detection-progress');
    const hwaccelResults = document.getElementById('hwaccel-results');
    const hwaccelAvailable = document.getElementById('hwaccel-available');
    const hwaccelUnavailable = document.getElementById('hwaccel-unavailable');
    const hwaccelType = document.getElementById('hwaccel-type');
    const hwaccelEncoders = document.getElementById('hwaccel-encoders');
    const capabilitiesJson = document.getElementById('capabilities-json-content');
    const editCapabilitiesButton = document.getElementById('edit-capabilities-button');
    const saveCapabilitiesButton = document.getElementById('save-capabilities-button');
    
    if (detectHardwareBtn && detectionProgress && hwaccelResults) {
        // Detect hardware capabilities
        detectHardwareBtn.addEventListener('click', function() {
            // Show progress
            detectHardwareBtn.disabled = true;
            detectionProgress.style.display = 'flex';
            
            // Start detection
            fetch('/onboarding/detect_hw_accel')
                .then(response => response.json())
                .then(data => {
                    // Hide progress
                    detectionProgress.style.display = 'none';
                    hwaccelResults.style.display = 'block';
                    
                    // Debug: Log the response data structure
                    console.log('Hardware acceleration data:', data);
                    
                    // Check if hardware acceleration is available
                    if (data && data.methods && data.methods.length > 0) {
                        // Show available section
                        hwaccelAvailable.style.display = 'block';
                        hwaccelUnavailable.style.display = 'none';
                        
                        // Update details with the recommended method
                        if (hwaccelType && data.recommended && data.recommended.method) {
                            hwaccelType.textContent = data.recommended.method;
                        } else if (hwaccelType && data.methods && data.methods.length > 0) {
                            hwaccelType.textContent = data.methods[0];
                        }
                        
                        // Update encoders list
                        if (hwaccelEncoders && data.methods) {
                            hwaccelEncoders.textContent = data.methods.join(', ');
                        }
                        
                        // Update JSON content
                        if (capabilitiesJson) {
                            capabilitiesJson.value = JSON.stringify(data, null, 2);
                        }
                    } else {
                        // Show unavailable section
                        hwaccelAvailable.style.display = 'none';
                        hwaccelUnavailable.style.display = 'block';
                    }
                    
                    // Re-enable button
                    detectHardwareBtn.disabled = false;
                })
                .catch(error => {
                    console.error('Error detecting hardware capabilities:', error);
                    
                    // Hide progress
                    detectionProgress.style.display = 'none';
                    
                    // Show error
                    hwaccelResults.style.display = 'block';
                    hwaccelAvailable.style.display = 'none';
                    hwaccelUnavailable.style.display = 'block';
                    
                    // Re-enable button
                    detectHardwareBtn.disabled = false;
                });
        });
        
        // Edit capabilities button
        if (editCapabilitiesButton && saveCapabilitiesButton && capabilitiesJson) {
            editCapabilitiesButton.addEventListener('click', function() {
                if (capabilitiesJson.readOnly) {
                    // Enable editing
                    capabilitiesJson.readOnly = false;
                    editCapabilitiesButton.textContent = 'Disable Editing';
                    capabilitiesJson.style.border = '2px solid #e74c3c';
                    capabilitiesJson.style.backgroundColor = '#fff9f9';
                    saveCapabilitiesButton.style.display = 'inline-block';
                } else {
                    // Disable editing
                    capabilitiesJson.readOnly = true;
                    editCapabilitiesButton.textContent = 'Enable Editing';
                    capabilitiesJson.style.border = '';
                    capabilitiesJson.style.backgroundColor = '';
                    saveCapabilitiesButton.style.display = 'none';
                }
            });
            
            // Save capabilities button
            saveCapabilitiesButton.addEventListener('click', function() {
                // Get the JSON content
                let capabilitiesData;
                try {
                    capabilitiesData = JSON.parse(capabilitiesJson.value);
                } catch (error) {
                    alert('Error: Invalid JSON format. Please check your formatting and try again.');
                    return;
                }
                
                // Save the capabilities
                fetch('/onboarding/save_hw_capabilities', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(capabilitiesData),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Disable editing
                        capabilitiesJson.readOnly = true;
                        editCapabilitiesButton.textContent = 'Enable Editing';
                        capabilitiesJson.style.border = '';
                        capabilitiesJson.style.backgroundColor = '';
                        saveCapabilitiesButton.style.display = 'none';
                        
                        // Update the textarea with the saved data
                        capabilitiesJson.value = JSON.stringify(data.capabilities, null, 2);
                        
                        // Show success message
                        alert('Hardware capabilities saved successfully!');
                    } else {
                        alert(`Error: ${data.message || 'Failed to save hardware capabilities'}`);
                    }
                })
                .catch(error => {
                    console.error('Error saving hardware capabilities:', error);
                    alert('Error: Failed to save hardware capabilities');
                });
            });
        }
    }
}