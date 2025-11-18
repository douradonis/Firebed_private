// Admin Groups Tab - AJAX delete, group details modal

function deleteGroupAjax(groupId, groupName) {
    if (!confirm(`Delete group "${groupName}" (will backup first if data exists)?`)) {
        return;
    }
    fetch(`/admin/groups/${groupId}/delete`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(resp => resp.json())
    .then(data => {
        if (data.ok || data.success) {
            alert('Group deleted (backup: ' + (data.backup_path || 'none') + ')');
            location.reload();
        } else {
            alert('Delete failed: ' + (data.error || data.message || 'Unknown error'));
        }
    })
    .catch(err => {
        alert('Error: ' + err);
    });
}

function showGroupDetailsModal(groupId, groupName) {
    fetch(`/admin/groups/${groupId}`, { headers: { 'Accept': 'application/json' } })
        .then(resp => {
            if (!resp.ok) throw new Error('Group not found');
            return resp.json();
        })
        .then(data => {
            const modal = document.getElementById('groupDetailsModal');
            if (!modal) {
                console.error('Modal not found');
                return;
            }
            
            const titleEl = modal.querySelector('.modal-title');
            const bodyEl = modal.querySelector('.modal-body');
            
            titleEl.textContent = `${groupName} - Details`;
            
            let html = `
                <div class="mb-3">
                    <h6>Group Information</h6>
                    <p><strong>Folder:</strong> <code>${data.data_folder}</code></p>
                    <p><strong>Size:</strong> ${data.folder_size_mb} MB</p>
                    <p><strong>Created:</strong> ${data.created_at}</p>
                </div>
                <div class="mb-3">
                    <h6>Members (${data.members.length})</h6>
            `;
            
            if (data.members && data.members.length > 0) {
                html += '<ul>';
                data.members.forEach(member => {
                    html += `<li>${member.username} <span class="badge badge-${member.role === 'admin' ? 'danger' : 'info'}">${member.role}</span></li>`;
                });
                html += '</ul>';
            } else {
                html += '<p class="text-muted">No members</p>';
            }
            
            html += '</div>';
            bodyEl.innerHTML = html;
            
            const bootstrapModal = new bootstrap.Modal(modal);
            bootstrapModal.show();
        })
        .catch(err => {
            alert('Error loading group details: ' + err);
        });
}
