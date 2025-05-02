document.addEventListener('DOMContentLoaded', function() {
    const hwAccelSelect = document.getElementById('hw_accel');
    const hwDeviceGroup = document.getElementById('hw_device_group');
    const hwFailoverGroup = document.getElementById('hw_failover_group');
    
    hwAccelSelect.addEventListener('change', function() {
        // Show device field only for methods that need it
        if (this.value === 'nvenc' || this.value === 'cuda' || this.value === 'vaapi') {
            hwDeviceGroup.style.display = 'block';
        } else {
            hwDeviceGroup.style.display = 'none';
            // Clear the device input if not using a supported method
            if (this.value === 'inherit' || this.value === '') {
                document.getElementById('hw_device').value = '';
            }
        }
        
        // Show failover option only when hardware acceleration is enabled or inherited
        if (this.value === '' || this.value === null) {
            hwFailoverGroup.style.display = 'none';
        } else {
            hwFailoverGroup.style.display = 'block';
        }
    });
    
    // Initial check
    if (hwAccelSelect.value === '') {
        hwFailoverGroup.style.display = 'none';
    }
});