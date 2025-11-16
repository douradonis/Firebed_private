# Phase 3: Lazy-Pull Data Loading Implementation Plan

## Objective
Expand the lazy-pull feature from just 2 admin detail views to ALL server operations that access group data. This enables the Render free tier to fetch missing data on-demand from Firebase, rather than requiring all data to be pre-populated locally.

## Current State Analysis

### Existing Lazy-Pull Implementation
- **Function**: `firebase_pull_group_to_local()` in `firebase_config.py` (lines 413-475)
- **Current Usage**: Only 2 call sites:
  - `admin_get_user_details()` (admin_panel.py:97)
  - `admin_get_group_details()` (admin_panel.py:234)
- **Status**: Both are defensive attempts (try/except when local data missing)

### Architecture Overview
- **Data Access Pattern**: Most routes use `group_path(*parts)` helper (app.py:1030)
- **Flow**: `group_path()` → `get_group_base_dir()` → `data/<group_folder>/...`
- **Problem**: If local folder is missing, operations fail before lazy-pull can trigger

### Key Data Access Points
1. **Admin Panel** (admin_panel.py)
   - `admin_list_all_users()` - Lists users, calculates group sizes
   - `admin_get_user_details()` - ✅ Already has lazy-pull (line 97)
   - `admin_get_group_details()` - ✅ Already has lazy-pull (line 234)
   - `admin_list_all_groups()` - Lists groups (currently may fail)
   - Backup operations

2. **Main Application** (app.py)
   - `/list` route (line 8635) - Reads Excel files (invoices_cache.json, etc.)
   - `/api/receipts` - Lists receipts
   - `/api/repeat_entry/list` - Lists repeat entries
   - `/api/profiles` - Lists profiles
   - Export operations (Kinitseis, Epsilon preview, etc.)
   - `/search/mark` - Searches for invoices
   - `/epsilon/preview` - Epsilon bridge operations
   - All routes that call `group_path()` indirectly

3. **Upload/File Operations**
   - Credential uploads
   - Receipt uploads
   - Excel imports

4. **Reporting & Export**
   - Excel exports
   - Kinitseis exports
   - VAT reports

## Implementation Strategy

### Phase 3a: Core Infrastructure (Priority 1)

**Goal**: Create smart lazy-pull mechanism at entry points

#### 1. Enhance firebase_config.py
- `firebase_pull_group_to_local()` - Already exists, verify it works correctly
- Add logging for all lazy-pull attempts (success/failure)
- Ensure subfolder structure is preserved (epsilon/, excel/, etc.)
- Handle symlinks and special files

**New helper function**:
```python
def ensure_group_data_local(group_folder: str, create_empty: bool = True) -> bool:
    """
    Ensure a group's data folder exists locally.
    If missing, attempt lazy-pull from Firebase.
    If Firebase also has no data, optionally create empty folder structure.
    Returns True if folder now exists and is accessible.
    """
```

#### 2. Enhance app.py entry points
- Add lazy-pull call at start of each route that accesses `group_path()`
- Specifically: Before any `os.path.exists(group_path(...))` check
- Wrap in try/except to gracefully degrade if Firebase unavailable

**Pattern**:
```python
@app.route("/some_data_route")
def some_data_view():
    # NEW: Ensure group data available
    try:
        firebase_config.ensure_group_data_local(active_group_folder)
    except Exception as e:
        logger.warning(f"Failed to lazy-pull group data: {e}")
    
    # Existing logic continues
    # If data wasn't available and pull failed, operations proceed gracefully
```

**Routes requiring this pattern**:
1. `/list` (list invoices) - Line 8635
2. `/api/receipts` (API endpoint) - ~line 2300+
3. `/api/repeat_entry/list` - ~line 2100+
4. `/api/profiles` - Search profiles
5. `/epsilon/preview` - Epsilon operations
6. `/export/fastimport/kinitseis` - Export operations
7. `/search/mark` - Invoice search
8. All `/api/*` routes that access group data

#### 3. Enhance admin_panel.py
- Add lazy-pull to `admin_list_all_groups()` - currently reads group sizes
- Add lazy-pull to backup operations - before accessing data
- Log all lazy-pull attempts in activity logs

### Phase 3b: Subfolder Materialization (Priority 2)

**Challenge**: `firebase_pull_group_to_local()` currently flattens structure
- Current: Converts `/groups/{group}/epsilon/invoices.json` → `data/{group}/epsilon_invoices.json`
- Issue: Nested folders not preserved; sub-subfolder structure lost

**Solution**:
- Enhance `firebase_pull_group_to_local()` to detect nested paths
- Recreate folder hierarchy: `data/{group}/epsilon/`, `data/{group}/excel/`, etc.
- Preserve empty directories

**Implementation**:
```python
def firebase_pull_group_to_local(group_name: str, local_data_root: str = None) -> bool:
    """Enhanced to:
    1. Detect nested keys like 'epsilon/invoices.json'
    2. Create subdirectories accordingly
    3. Handle compressed payloads
    4. Log progress
    """
```

### Phase 3c: Testing & Validation (Priority 3)

**Test Scenarios**:
1. **No Local Data**: Delete `data/{group}/` folder completely
   - Access admin panel → Should lazy-pull and work
   - Access list view → Should lazy-pull and work
   - Access exports → Should lazy-pull and work

2. **Partial Data**: Delete specific subfolder (e.g., `epsilon/`)
   - Access epsilon preview → Should lazy-pull just that subfolder
   - Other operations unaffected

3. **Firebase Missing**: Simulate empty Firebase
   - Operations should gracefully degrade
   - Create empty folder structure
   - Log warning but don't crash

4. **Large Groups**: Test with >100MB group
   - Compression/decompression works
   - Progress logging visible
   - No timeout issues

## File Changes Summary

### firebase_config.py
- ✅ Keep: `firebase_pull_group_to_local()` - Already works well
- 🔄 Enhance: Add subfolder detection and materialization
- ➕ Add: `ensure_group_data_local()` wrapper function
- ➕ Add: Verbose logging for lazy-pull attempts
- ➕ Add: Compression support for large payloads

### admin_panel.py
- ➕ Add: Lazy-pull to `admin_list_all_groups()`
- ➕ Add: Lazy-pull to all backup operations
- ➕ Add: Activity logging for lazy-pull events

### app.py
- ➕ Add: Lazy-pull calls at start of routes (10+ routes)
- ➕ Add: Helper method or decorator to standardize pattern
- 📊 No breaking changes to existing logic

### templates & static/
- No changes required (lazy-pull is server-side)

## Rollout Plan

### Stage 1: Foundation (This PR)
- Enhance `firebase_pull_group_to_local()` for subfolder support
- Create `ensure_group_data_local()` wrapper
- Add comprehensive logging
- Test with admin panel

### Stage 2: Gradual Route Integration
- Add lazy-pull to highest-traffic routes first (/list, /api/receipts)
- Test each route individually
- Monitor logs for failures

### Stage 3: Complete Coverage
- Add lazy-pull to all remaining routes
- Final integration testing
- Deploy to Render

## Success Metrics

✅ Admin panel works even with empty `data/` folder
✅ `/list` view works after lazy-pull
✅ Export operations work after lazy-pull
✅ Subfolder structure preserved (epsilon/, excel/, etc.)
✅ Activity logs track all lazy-pull events
✅ No crashes due to missing data (graceful degradation)
✅ Firebase unavailability doesn't break operations

## Risk Mitigation

- **Risk**: Lazy-pull too slow for large groups
  - Mitigation: Compress on Firebase, add timeout handling
  
- **Risk**: Concurrent requests trigger duplicate pulls
  - Mitigation: Use file locking, or accept duplicate pulls (minimal cost)
  
- **Risk**: Subfolder structure lost during pull
  - Mitigation: Detect nested keys, preserve paths
  
- **Risk**: Firebase credentials unavailable
  - Mitigation: Graceful degradation, clear logging

## Timeline

- **Now**: Phase 3a (Core infrastructure) - ~2 hours
- **After**: Phase 3b (Subfolder support) - ~1 hour
- **Then**: Phase 3c (Testing) - ~1-2 hours
- **Total**: ~4-5 hours development + testing

## Next Steps

1. ✅ Create this plan document
2. → Enhance `firebase_pull_group_to_local()` for subfolders
3. → Create `ensure_group_data_local()` wrapper
4. → Test with admin panel (group list)
5. → Add lazy-pull to `/list` route
6. → Add lazy-pull to remaining routes
7. → End-to-end testing
8. → Deploy to Render
