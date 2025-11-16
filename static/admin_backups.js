// Admin Backups Tab - AJAX restore with confirmation

function restoreBackupAjax(backupName) {
    const groupId = document.getElementById(`groupSelect_${backupName}`).value;
    if (!groupId) {
        alert('Please select a group');
        return;
    }
    
    if (!confirm(`Restore backup to selected group? This will overwrite existing data.`)) {
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
