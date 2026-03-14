/**
 * Completed transcodes page logic - Replace functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const replaceModal = document.getElementById('replaceModal');
    if (!replaceModal) return;

    const confirmBtn = replaceModal.querySelector('.replace-confirm-btn');
    const cancelBtn = replaceModal.querySelector('.replace-cancel-btn');
    const closeBtn = replaceModal.querySelector('.close-modal');
    let currentFilename = null;

    // Open modal on replace button click
    document.querySelectorAll('.replace-button').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            currentFilename = this.getAttribute('data-filename');
            replaceModal.style.display = 'flex';
        });
    });

    // Close modal
    function closeModal() {
        replaceModal.style.display = 'none';
        currentFilename = null;
    }

    cancelBtn.addEventListener('click', closeModal);
    closeBtn.addEventListener('click', closeModal);
    replaceModal.addEventListener('click', function(e) {
        if (e.target === replaceModal) closeModal();
    });

    // Confirm replace
    confirmBtn.addEventListener('click', function() {
        if (!currentFilename) return;

        var filenameToReplace = currentFilename;
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Replacing...';

        fetch('/api/transcode/replace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: filenameToReplace })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            closeModal();
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Replace';

            if (data.success) {
                // Find and remove the card with fade-out animation
                var card = document.querySelector('.replace-button[data-filename="' + filenameToReplace + '"]');
                if (card) {
                    card = card.closest('.transcode-card');
                    if (card) {
                        card.style.transition = 'opacity 0.4s, transform 0.4s';
                        card.style.opacity = '0';
                        card.style.transform = 'scale(0.95)';
                        setTimeout(function() {
                            card.remove();
                            // Check if grid is now empty
                            var grid = document.querySelector('.transcode-grid');
                            if (grid && grid.children.length === 0) {
                                grid.outerHTML = '<div class="empty-state"><div class="empty-state-mascot"><img src="/static/img/anvil-thinking.png" alt="No completed transcodes"></div><p>No completed transcodes found.</p></div>';
                            }
                        }, 400);
                    }
                }
                showNotification(data.message, 'success');
            } else {
                showNotification(data.message || 'Failed to replace file', 'error');
            }
        })
        .catch(function(err) {
            closeModal();
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Replace';
            showNotification('Error: ' + err.message, 'error');
        });
    });
});
