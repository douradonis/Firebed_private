// Admin Users Tab - AJAX delete, activity modal, storage display

function deleteUserAjax(userId, username) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) {
        return;
    }
    
    fetch(`/admin/users/${userId}/delete`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(resp => resp.json())
    .then(data => {
        if (data.ok || data.success) {
            alert('User deleted');
            location.reload();
        } else {
            alert('Delete failed: ' + (data.error || data.message || 'Unknown error'));
        }
    })
    .catch(err => {
        alert('Error: ' + err);
    });
}

function showUserActivityModal(userId, username) {
    // Fetch user details (activity + storage)
    fetch(`/admin/users/${userId}`)
        .then(resp => {
            if (!resp.ok) throw new Error('User not found');
            return resp.json();
        })
        .then(data => {
            // Open modal with user details
            const modal = document.getElementById('userActivityModal');
            if (!modal) {
                console.error('Modal not found');
                return;
            }
            
            const titleEl = modal.querySelector('.modal-title');
            const bodyEl = modal.querySelector('.modal-body');
            
            titleEl.textContent = `${username} - Activity & Storage`;
            
            let html = `
                <div class="mb-3">
                    <h6>Storage Summary</h6>
                    <p><strong>Total:</strong> ${data.total_size_mb} MB</p>
                </div>
                <div class="mb-3">
                    <h6>Recent Activity</h6>
            `;
            
            if (data.recent_activity && data.recent_activity.length > 0) {
                html += '<ul style="max-height: 300px; overflow-y: auto;">';
                data.recent_activity.forEach(act => {
                    html += `<li><small>${act.timestamp} - ${act.action} (${act.group})</small></li>`;
                });
                html += '</ul>';
            } else {
                html += '<p class="text-muted">No recent activity</p>';
            }
            
            html += '</div>';
            bodyEl.innerHTML = html;
            
            // Show modal
            const bootstrapModal = new bootstrap.Modal(modal);
            bootstrapModal.show();
        })
        .catch(err => {
            alert('Error loading user details: ' + err);
        });
}
