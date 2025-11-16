// Admin Activity Logs Tab - filtering, pagination

document.addEventListener('DOMContentLoaded', function() {
    const filterForm = document.getElementById('activityFilterForm');
    const logsTable = document.getElementById('logsTable');
    
    if (filterForm) {
        filterForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const group = document.getElementById('filterGroup').value || '';
            const action = document.getElementById('filterAction').value || '';
            const limit = document.getElementById('filterLimit').value || 100;
            
            // Fetch filtered logs via API
            const url = `/api/admin/activity-logs?group=${encodeURIComponent(group)}&action=${encodeURIComponent(action)}&limit=${limit}`;
            
            fetch(url)
                .then(resp => resp.json())
                .then(data => {
                    if (data && Array.isArray(data)) {
                        renderLogs(data);
                    } else {
                        alert('Failed to fetch logs');
                    }
                })
                .catch(err => alert('Error: ' + err));
        });
    }
    
    function renderLogs(logs) {
        const tbody = logsTable.querySelector('tbody');
        tbody.innerHTML = '';
        
        logs.forEach(log => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><small>${formatTimestamp(log.timestamp)}</small></td>
                <td>${log.user_id || 'system'}</td>
                <td>${log.group || '-'}</td>
                <td><code>${log.action}</code></td>
                <td><small>${JSON.stringify(log.details || {})}</small></td>
            `;
            tbody.appendChild(row);
        });
        
        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No logs found</td></tr>';
        }
    }
    
    function formatTimestamp(ts) {
        if (!ts) return '';
        try {
            const date = new Date(ts);
            return date.toLocaleString();
        } catch (e) {
            return ts;
        }
    }
});
