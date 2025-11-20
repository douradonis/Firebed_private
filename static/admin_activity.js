// Admin Activity Logs Tab - filtering, pagination

document.addEventListener('DOMContentLoaded', function() {
    const filterForm = document.getElementById('activityFilterForm');
    const logsTable = document.getElementById('logsTable');
    const filterGroup = document.getElementById('filterGroup');
    const filterAction = document.getElementById('filterAction');
    const filterLimit = document.getElementById('filterLimit');
    
    let debounceTimer;
    
    // Function to perform the search
    function performSearch() {
        const group = filterGroup.value || '';
        const action = filterAction.value || '';
        const limit = filterLimit.value || 100;
        
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
    }
    
    if (filterForm) {
        // Handle form submit (e.g., pressing Enter)
        filterForm.addEventListener('submit', function(e) {
            e.preventDefault();
            performSearch();
        });
        
        // Live search on input with debouncing
        if (filterGroup) {
            filterGroup.addEventListener('input', function() {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(performSearch, 500);
            });
        }
        
        if (filterAction) {
            filterAction.addEventListener('input', function() {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(performSearch, 500);
            });
        }
        
        if (filterLimit) {
            filterLimit.addEventListener('input', function() {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(performSearch, 500);
            });
        }
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
