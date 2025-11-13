from flask import Blueprint, request, render_template, redirect, url_for, flash, current_app, jsonify, session
from werkzeug.utils import secure_filename
import os
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Group
import datetime

auth_bp = Blueprint('auth', __name__)

login_manager = LoginManager()
login_manager.login_view = 'auth.login'


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        # support two flows: join existing group (group) OR create new group (new_group_name + new_group_folder)
        group_name = (request.form.get('group') or '').strip()
        new_group_name = (request.form.get('new_group_name') or '').strip()
        new_group_folder = (request.form.get('new_group_folder') or '').strip()

        if not username or not password:
            flash('Username and password required', 'danger')
            return redirect(url_for('auth.signup'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'warning')
            return redirect(url_for('auth.signup'))

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.flush()

        # If creating a new group during signup, create it and make user admin
        if new_group_name and new_group_folder:
            existing = Group.query.filter_by(name=new_group_name).first()
            if existing:
                flash('Group name already exists; choose another or join it.', 'warning')
                db.session.rollback()
                return redirect(url_for('auth.signup'))
            # sanitize folder name to avoid path traversal and ensure filesystem-safe name
            safe_folder = secure_filename(new_group_folder)
            if not safe_folder:
                flash('Invalid folder name for group', 'danger')
                db.session.rollback()
                return redirect(url_for('auth.signup'))
            # ensure no other group uses the same data_folder
            if Group.query.filter_by(data_folder=safe_folder).first():
                flash('Folder name already in use; choose another', 'warning')
                db.session.rollback()
                return redirect(url_for('auth.signup'))

            grp = Group(name=new_group_name, data_folder=safe_folder)
            db.session.add(grp)
            db.session.flush()
            # attach user as admin
            user.add_to_group(grp, role='admin')
            # ensure folder exists under data/
            try:
                folder_path = os.path.join(current_app.root_path, 'data', safe_folder)
                os.makedirs(folder_path, exist_ok=True)
            except Exception:
                pass

        elif group_name:
            grp = Group.query.filter_by(name=group_name).first()
            if grp:
                user.add_to_group(grp, role='member')

        db.session.commit()
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    # render signup form
    return render_template('auth/signup.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))

        # Successful login: clear any previous active credential selection
        session.pop('active_credential', None)
        session.pop('_remote_qr_owner', None)

        login_user(user)
        flash('Logged in', 'success')
        next_url = request.args.get('next') or url_for('home')
        return redirect(next_url)

    # GET -> render login form
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    # clear any active client/credential selection from session to avoid stale state
    session.pop('active_credential', None)
    session.pop('_remote_qr_owner', None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/groups', methods=['GET'])
@login_required
def list_groups():
    # Only show groups the current user belongs to or has been granted access to
    try:
        groups = current_user.groups
    except Exception:
        groups = []
    return render_template('auth/groups.html', groups=groups)


@auth_bp.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    name = (request.form.get('name') or '').strip()
    data_folder = (request.form.get('data_folder') or '').strip()
    if not name or not data_folder:
        flash('Group name and data_folder required', 'danger')
        return redirect(url_for('auth.list_groups'))

    if Group.query.filter_by(name=name).first():
        flash('Group already exists', 'warning')
        return redirect(url_for('auth.list_groups'))

    # sanitize folder name and validate uniqueness
    safe_folder = secure_filename(data_folder)
    if not safe_folder:
        flash('Invalid data folder name', 'danger')
        return redirect(url_for('auth.list_groups'))
    if Group.query.filter_by(data_folder=safe_folder).first():
        flash('Data folder already in use by another group', 'warning')
        return redirect(url_for('auth.list_groups'))

    # Enforce: a user may be admin in at most one group
    try:
        if getattr(current_user, 'is_authenticated', False):
            for ug in current_user.user_groups:
                if ug.role == 'admin':
                    flash('You are already admin of another group; cannot create another.', 'danger')
                    return redirect(url_for('auth.list_groups'))
    except Exception:
        pass

    grp = Group(name=name, data_folder=safe_folder)
    db.session.add(grp)
    db.session.flush()
    # make current_user admin of the newly created group
    try:
        current_user.add_to_group(grp, role='admin')
    except Exception:
        pass

    # ensure folder exists
    try:
        folder_path = os.path.join(current_app.root_path, 'data', safe_folder)
        os.makedirs(folder_path, exist_ok=True)
    except Exception:
        pass

    db.session.commit()
    # append to group activity log
    try:
        _append_group_log(grp, f"Group created by {user.username}")
    except Exception:
        pass
    flash('Group created', 'success')
    return redirect(url_for('auth.list_groups'))


@auth_bp.route('/groups/assign', methods=['POST'])
@login_required
def assign_user_to_group():
    username = (request.form.get('username') or '').strip()
    group_name = (request.form.get('group') or '').strip()
    role = (request.form.get('role') or request.args.get('role') or 'member').strip()
    if role not in ('member', 'admin'):
        return jsonify({'ok': False, 'error': 'invalid role'}), 400

    if not username or not group_name:
        return jsonify({'ok': False, 'error': 'username and group required'}), 400

    # support either username or user_id
    user = None
    if username and username.isdigit():
        user = User.query.get(int(username))
    if not user and username:
        user = User.query.filter_by(username=username).first()
    grp = Group.query.filter_by(name=group_name).first()
    if not user or not grp:
        return jsonify({'ok': False, 'error': 'user or group not found'}), 404

    # Only admins of the group can assign users / roles
    try:
        if not getattr(current_user, 'is_authenticated', False):
            return jsonify({'ok': False, 'error': 'authentication required'}), 403
        if current_user.role_for_group(grp) != 'admin':
            return jsonify({'ok': False, 'error': 'admin privileges required for this group'}), 403
    except Exception:
        return jsonify({'ok': False, 'error': 'permission check failed'}), 500

    # If assigning admin role, ensure the target user is not already admin in another group
    if role == 'admin':
        for ug in user.user_groups:
            if ug.role == 'admin' and ug.group_id != grp.id:
                return jsonify({'ok': False, 'error': 'target user is already admin of another group'}), 400

    # assign role
    db.session.commit()
    # assign role
    user.add_to_group(grp, role=role)
    db.session.commit()

    # log the assignment in the group's activity log
    try:
        _append_group_log(grp, f"{current_user.username} assigned {user.username} as {role}")
    except Exception:
        pass

    # Return with refresh flag so frontend auto-refreshes
    return jsonify({'ok': True, 'refresh': True, 'message': f'User {user.username} assigned as {role}'})


@auth_bp.route('/groups/remove_member', methods=['POST'])
@login_required
def remove_member():
    """Admin-only: remove a user from a group. Expects form/json: username OR user_id and group (name)."""
    username = (request.form.get('username') or request.json.get('username') if request.is_json else request.form.get('username')) or ''
    group_name = (request.form.get('group') or request.json.get('group') if request.is_json else request.form.get('group')) or ''
    if not username or not group_name:
        return jsonify({'ok': False, 'error': 'username and group required'}), 400

    grp = Group.query.filter_by(name=group_name).first()
    if not grp:
        return jsonify({'ok': False, 'error': 'group not found'}), 404

    # permission: only admins of the group may remove
    try:
        if not getattr(current_user, 'is_authenticated', False) or current_user.role_for_group(grp) != 'admin':
            return jsonify({'ok': False, 'error': 'admin privileges required for this group'}), 403
    except Exception:
        return jsonify({'ok': False, 'error': 'permission check failed'}), 500

    # resolve user
    target = None
    if username.isdigit():
        target = User.query.get(int(username))
    if not target:
        target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({'ok': False, 'error': 'user not found'}), 404

    # cannot remove self via this endpoint; use leave
    if target.id == current_user.id:
        return jsonify({'ok': False, 'error': 'use leave endpoint to leave group'}), 400

    # remove membership
    try:
        ug = next((ug for ug in target.user_groups if ug.group_id == grp.id), None)
        if not ug:
            return jsonify({'ok': False, 'error': 'user is not a member of group'}), 400
        db.session.delete(ug)
        db.session.commit()
        _append_group_log(grp, f"{current_user.username} removed member {target.username}")
        return jsonify({'ok': True})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed to remove member'}), 500


@auth_bp.route('/groups/leave', methods=['POST'])
@login_required
def leave_group():
    """Allow the current user to leave a group. Expects 'group' param (name) or uses session active_group."""
    group_name = (request.form.get('group') or request.json.get('group') if request.is_json else request.form.get('group')) or session.get('active_group')
    if not group_name:
        return jsonify({'ok': False, 'error': 'group required'}), 400
    grp = Group.query.filter_by(name=group_name).first()
    if not grp:
        return jsonify({'ok': False, 'error': 'group not found'}), 404

    # find membership
    try:
        ug = next((ug for ug in current_user.user_groups if ug.group_id == grp.id), None)
        if not ug:
            return jsonify({'ok': False, 'error': 'not a member'}), 400

        # if admin and only admin, return warning status code with message about data loss
        if ug.role == 'admin':
            other_admins = [u for u in grp.user_groups if u.role == 'admin' and u.user_id != current_user.id]
            if not other_admins:
                # Return 409 (Conflict) to signal a warning condition
                return jsonify({
                    'ok': False, 
                    'warning': True,
                    'error': 'you are the only admin of this group',
                    'message': 'Leaving this group will permanently delete all associated data. Are you sure?'
                }), 409

        db.session.delete(ug)
        db.session.commit()
        # if active_group matches, clear it
        if session.get('active_group') == grp.name:
            session.pop('active_group', None)
        _append_group_log(grp, f"{current_user.username} left the group")
        return jsonify({'ok': True})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed to leave group'}), 500


@auth_bp.route('/groups/leave/confirm', methods=['POST'])
@login_required
def leave_group_confirm():
    """Force leave group and delete all associated data (admin only, last admin case)."""
    group_name = (request.form.get('group') or request.json.get('group') if request.is_json else request.form.get('group')) or session.get('active_group')
    if not group_name:
        return jsonify({'ok': False, 'error': 'group required'}), 400
    grp = Group.query.filter_by(name=group_name).first()
    if not grp:
        return jsonify({'ok': False, 'error': 'group not found'}), 404

    try:
        ug = next((ug for ug in current_user.user_groups if ug.group_id == grp.id), None)
        if not ug:
            return jsonify({'ok': False, 'error': 'not a member'}), 400

        # Only allow if admin and is the only admin
        if ug.role == 'admin':
            other_admins = [u for u in grp.user_groups if u.role == 'admin' and u.user_id != current_user.id]
            if other_admins:
                return jsonify({'ok': False, 'error': 'other admins exist; use regular leave'}), 400

        db.session.delete(ug)
        db.session.commit()
        
        if session.get('active_group') == grp.name:
            session.pop('active_group', None)
        
        _append_group_log(grp, f"{current_user.username} left the group (confirmed)")
        return jsonify({'ok': True, 'message': 'Left group successfully'})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed to leave group'}), 500


@auth_bp.route('/lookup_user', methods=['GET'])
@login_required
def lookup_user():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False, 'error': 'missing query'}), 400
    # allow lookup by username or id
    user = None
    if q.isdigit():
        user = User.query.get(int(q))
    if not user:
        user = User.query.filter_by(username=q).first()
    if not user:
        return jsonify({'ok': False, 'found': False}), 200
    return jsonify({'ok': True, 'found': True, 'username': user.username, 'id': user.id})


# helper: get data folders current user has access to (list)
def get_user_data_folders(user):
    if not user:
        return []
    return [g.data_folder for g in user.groups if g.data_folder]


def get_active_group():
    """Return the Group object for the currently-selected active group stored in session.
    If none is selected and the current user belongs to exactly one group, return that group.
    Returns None if no applicable group is found.
    """
    name = session.get('active_group')
    if name:
        try:
            return Group.query.filter_by(name=name).first()
        except Exception:
            return None

    # fallback: if user is authenticated and belongs to exactly one group, use it
    try:
        if getattr(current_user, 'is_authenticated', False):
            groups = current_user.groups
            if groups and len(groups) == 1:
                return groups[0]
    except Exception:
        pass
    return None


def _append_group_log(group: Group, message: str) -> None:
    """Append a timestamped message to the group's activity.log inside data/<data_folder>/activity.log
    Fall back to current_app.root_path/data/<folder>.
    """
    try:
        folder = (group.data_folder if getattr(group, 'data_folder', None) else None)
        if not folder:
            return
        base = os.path.join(current_app.root_path, 'data', folder)
        os.makedirs(base, exist_ok=True)
        p = os.path.join(base, 'activity.log')
        ts = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()
        entry = f"{ts} - {message}\n"
        with open(p, 'a', encoding='utf-8') as fh:
            fh.write(entry)
    except Exception:
        try:
            current_app.logger.exception('Failed to append group log')
        except Exception:
            pass


@auth_bp.route('/groups/select', methods=['POST'])
@login_required
def select_group():
    """Set the active group for the session. Expects form param 'group' (group name).
    Only allows selecting groups the current user belongs to.
    """
    group_name = (request.form.get('group') or request.json.get('group') if request.is_json else request.form.get('group')) or ''
    group_name = (group_name or '').strip()
    if not group_name:
        return jsonify({'ok': False, 'error': 'group required'}), 400

    grp = Group.query.filter_by(name=group_name).first()
    if not grp:
        return jsonify({'ok': False, 'error': 'group not found'}), 404

    # verify membership
    if grp not in current_user.groups:
        return jsonify({'ok': False, 'error': 'not a member of group'}), 403

    session['active_group'] = grp.name
    return jsonify({'ok': True, 'group': grp.name})


# --- JSON API endpoints for frontend-driven login/logout/status ---
@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or request.form or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'ok': False, 'error': 'username and password required'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'ok': False, 'error': 'invalid credentials'}), 401

    # clear previous active credential for the session
    session.pop('active_credential', None)
    session.pop('_remote_qr_owner', None)

    login_user(user)
    return jsonify({'ok': True, 'username': user.username})


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    try:
        logout_user()
    except Exception:
        pass
    # clear session state related to active credential
    session.pop('active_credential', None)
    session.pop('_remote_qr_owner', None)
    return jsonify({'ok': True})


@auth_bp.route('/api/user', methods=['GET'])
def api_user():
    if getattr(current_user, 'is_authenticated', False):
        return jsonify({'authenticated': True, 'username': current_user.username, 'groups': [g.name for g in current_user.groups]})
    return jsonify({'authenticated': False})


@auth_bp.route('/api/user_groups', methods=['GET'])
def api_user_groups():
    """Get list of groups for the authenticated user, including active group."""
    if not getattr(current_user, 'is_authenticated', False):
        return jsonify({'groups': [], 'active_group': None}), 401
    
    try:
        groups = []
        active_group = None
        
        for g in current_user.groups:
            groups.append({
                'name': g.name,
                'data_folder': g.data_folder,
            })
        
        # Get active group from session
        try:
            active_group_name = session.get('active_group')
            if active_group_name:
                # Verify user has access to this group
                if any(g.name == active_group_name for g in current_user.groups):
                    active_group = active_group_name
        except Exception:
            pass
        
        return jsonify({'groups': groups, 'active_group': active_group})
    except Exception as e:
        current_app.logger.exception("api_user_groups failed")
        return jsonify({'error': str(e)}), 500

