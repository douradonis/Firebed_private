// Admin Backups Tab - AJAX restore with confirmation

// ============================================================================
// LOCAL BACKUPS
// ============================================================================

function restoreLocalBackupAjax(backupName) {
    const groupId = document.getElementById(`groupSelect_${backupName}`).value;
    if (!groupId) {
        alert('Please select a group');
        return;
    }
    
    if (!confirm(`Restore local backup to selected group? This will overwrite existing data.`)) {
        return;
    }
    
    const formData = new FormData();
    formData.append('group_id', groupId);
    
    fetch(`/admin/backups/restore/${encodeURIComponent(backupName)}`, {
        method: 'POST',
        body: formData
    })
    .then(resp => resp.json())
    .then(data => {
        if (data.ok || data.success) {
            alert('Restore successful');
            location.reload();
        } else {
            alert('Restore failed: ' + (data.error || data.message));
        }
    })
    .catch(err => {
        alert('Error: ' + err);
    });
}

// Keep old name for backward compatibility
function restoreBackupAjax(backupName) {
    restoreLocalBackupAjax(backupName);
}

// ============================================================================
// REMOTE BACKUPS (Firebase)
// ============================================================================

let remoteBackupList = [];
let selectedBackupPath = null;

function loadRemoteBackups() {
    const container = document.getElementById('remoteBackupsContainer');
    container.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div> Loading remote backups...';
    
    fetch('/admin/api/backup/list')
        .then(resp => resp.json())
        .then(data => {
            if (!data.success) {
                container.innerHTML = `<div class="alert alert-danger">Failed to load: ${data.error || 'Unknown error'}</div>`;
                return;
            }
            
            remoteBackupList = data.backups || [];
            renderRemoteBackups();
        })
        .catch(err => {
            container.innerHTML = `<div class="alert alert-danger">Error: ${err}</div>`;
        });
}

function renderRemoteBackups() {
    const container = document.getElementById('remoteBackupsContainer');
    
    if (!remoteBackupList || remoteBackupList.length === 0) {
        container.innerHTML = '<p class="text-muted">No remote backups available in Firebase</p>';
        return;
    }
    
    let html = '<table class="table table-striped"><thead class="table-dark"><tr><th>Backup Path</th><th>Size</th><th>Created</th><th>Actions</th></tr></thead><tbody>';
    
    remoteBackupList.forEach(backup => {
        html += `
            <tr>
                <td><code>${backup.name}</code></td>
                <td>${backup.size_mb} MB</td>
                <td>${backup.created_at}</td>
                <td>
                    <button class="btn btn-sm btn-success" onclick="openRemoteRestoreModal('${backup.name}')">Restore</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteRemoteBackup('${backup.name}')">Delete</button>
                </td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

function openRemoteRestoreModal(backupPath) {
    selectedBackupPath = backupPath;
    document.getElementById('modalBackupPath').textContent = `Backup: ${backupPath}`;
    document.getElementById('targetGroupId').value = '';
    document.getElementById('selectAllGroups').checked = false;
    document.getElementById('groupChecklistContainer').innerHTML = '';
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('remoteRestoreModal'));
    modal.show();
}

function toggleAllGroups() {
    const checked = document.getElementById('selectAllGroups').checked;
    const checkboxes = document.querySelectorAll('.groupCheckbox');
    checkboxes.forEach(cb => cb.checked = checked);
}

function doRemoteRestore() {
    if (!selectedBackupPath) {
        alert('No backup selected');
        return;
    }
    
    const targetGroupId = document.getElementById('targetGroupId').value;
    const selectedCheckboxes = document.querySelectorAll('.groupCheckbox:checked');
    
    let groups = null;
    if (selectedCheckboxes.length > 0) {
        groups = Array.from(selectedCheckboxes).map(cb => cb.value);
    }
    
    if (!targetGroupId && (!groups || groups.length === 0)) {
        alert('Please select either a target group or specific groups to restore');
        return;
    }
    
    if (!confirm('Restore from remote backup? This will overwrite existing data.')) {
        return;
    }
    
    const payload = {
        backup_path: selectedBackupPath,
        target_group_id: targetGroupId ? parseInt(targetGroupId) : null,
        groups: groups
    };
    
    fetch('/admin/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(resp => resp.json())
    .then(data => {
        if (data.success) {
            alert(`Restore successful. Restored groups: ${(data.restored || []).join(', ')}`);
            // Hide modal
            bootstrap.Modal.getInstance(document.getElementById('remoteRestoreModal')).hide();
            location.reload();
        } else {
            alert(`Restore failed: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(err => alert(`Error: ${err}`));
}

function deleteRemoteBackup(backupPath) {
    if (!confirm(`Delete remote backup: ${backupPath}? This cannot be undone.`)) {
        return;
    }
    
    fetch('/admin/api/backup', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: backupPath })
    })
    .then(resp => resp.json())
    .then(data => {
        if (data.success) {
            alert('Backup deleted');
            loadRemoteBackups();
        } else {
            alert(`Delete failed: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(err => alert(`Error: ${err}`));
}
