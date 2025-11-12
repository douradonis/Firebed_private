from flask import Blueprint, request, render_template, redirect, url_for, flash, current_app, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Group

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
            grp = Group(name=new_group_name, data_folder=new_group_folder)
            db.session.add(grp)
            db.session.flush()
            # attach user as admin
            user.add_to_group(grp, role='admin')
            # ensure folder exists under data/
            try:
                import os
                folder_path = os.path.join(current_app.root_path, 'data', new_group_folder)
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

    login_user(user)
    flash('Logged in', 'success')
    next_url = request.args.get('next') or url_for('home')
    return redirect(next_url)

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/groups', methods=['GET'])
@login_required
def list_groups():
    groups = Group.query.all()
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

    grp = Group(name=name, data_folder=data_folder)
    db.session.add(grp)
    db.session.flush()
    # make current_user admin of the newly created group
    try:
        current_user.add_to_group(grp, role='admin')
    except Exception:
        pass

    # ensure folder exists
    try:
        import os
        folder_path = os.path.join(current_app.root_path, 'data', data_folder)
        os.makedirs(folder_path, exist_ok=True)
    except Exception:
        pass

    db.session.commit()
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

    # assign role
    user.add_to_group(grp, role=role)
    db.session.commit()

    return jsonify({'ok': True})


# helper: get data folders current user has access to (list)
def get_user_data_folders(user):
    if not user:
        return []
    return [g.data_folder for g in user.groups if g.data_folder]


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

    login_user(user)
    return jsonify({'ok': True, 'username': user.username})


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    try:
        logout_user()
    except Exception:
        pass
    return jsonify({'ok': True})


@auth_bp.route('/api/user', methods=['GET'])
def api_user():
    if getattr(current_user, 'is_authenticated', False):
        return jsonify({'authenticated': True, 'username': current_user.username, 'groups': [g.name for g in current_user.groups]})
    return jsonify({'authenticated': False})
