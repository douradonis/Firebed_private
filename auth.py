from flask import Blueprint, request, render_template, redirect, url_for, flash, current_app, jsonify, session
from werkzeug.utils import secure_filename
import os
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import firebase_config
from models import db, User, Group
import datetime
from firebase_auth_handlers import FirebaseAuthHandler
import email_utils

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
            flash('Απαιτείται όνομα χρήστη και κωδικός πρόσβασης', 'danger')
            return redirect(url_for('auth.signup'))

        if User.query.filter_by(username=username).first():
            flash('Το όνομα χρήστη υπάρχει ήδη', 'warning')
            return redirect(url_for('auth.signup'))

        # Try to register user in Firebase (if enabled). If successful, store firebase_uid.
        firebase_uid = None
        try:
            success, uid, err = FirebaseAuthHandler.register_user(username, password, display_name=username)
            if success and uid:
                firebase_uid = uid
        except Exception:
            # If Firebase fails or not enabled, continue with local-only user
            firebase_uid = None

        user = User(username=username)
        user.email = username
        user.set_password(password)
        if firebase_uid:
            user.firebase_uid = firebase_uid

        db.session.add(user)
        db.session.flush()

        # If creating a new group during signup, create it and make user admin
        if new_group_name and new_group_folder:
            existing = Group.query.filter_by(name=new_group_name).first()
            if existing:
                flash('Το όνομα ομάδας υπάρχει ήδη. Επιλέξτε άλλο ή εγγραφείτε σε αυτή.', 'warning')
                db.session.rollback()
                return redirect(url_for('auth.signup'))
            # sanitize folder name to avoid path traversal and ensure filesystem-safe name
            safe_folder = secure_filename(new_group_folder)
            if not safe_folder:
                flash('Μη έγκυρο όνομα φακέλου για ομάδα', 'danger')
                db.session.rollback()
                return redirect(url_for('auth.signup'))
            # ensure no other group uses the same data_folder
            if Group.query.filter_by(data_folder=safe_folder).first():
                flash('Το όνομα φακέλου χρησιμοποιείται ήδη. Επιλέξτε άλλο', 'warning')
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

        # If we registered in Firebase, generate a verification link via Firebase Admin SDK
        try:
            if firebase_uid:
                ok, link_or_err = FirebaseAuthHandler.generate_email_verification_link(user.email)
                if ok:
                    # Try to send verification email via SMTP; fallback to logging
                    verify_link = link_or_err
                    app_url = os.getenv('APP_URL', 'http://localhost:5001')
                    logo_url = f"{app_url}/icons/scanmydata_logo_3000w.png"
                    html_body = f"""
                    <html>
                        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                                <div style="text-align: center; margin-bottom: 30px;">
                                    <img src="{logo_url}" alt="ScanmyData" style="height: 60px; width: auto;">
                                </div>
                                <h2 style="color: #0ea5e9;">Επαλήθευση Email</h2>
                                <p>Γεια σου {user.username},</p>
                                <p>Παρακαλώ επαλήθευσε τη διεύθυνση email σου πατώντας τον παρακάτω σύνδεσμο:</p>
                                <p style="margin: 25px 0;">
                                    <a href="{verify_link}" style="background-color: #0ea5e9; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">Επαλήθευση Email</a>
                                </p>
                                <p><small style="color: #6b7280;">Εάν δεν δημιούργησες αυτόν τον λογαριασμό, παρακαλώ αγνόησε αυτό το email.</small></p>
                                <div style="text-align: center; margin-top: 30px;">
                                    <img src="{logo_url}" alt="ScanmyData" style="height: 40px; width: auto; opacity: 0.6;">
                                </div>
                            </div>
                        </body>
                    </html>
                    """
                    sent = email_utils.send_email(user.email, 'Επαλήθευση Email - ScanmyData', html_body)
                    if sent:
                        flash('Ο λογαριασμός δημιουργήθηκε! Ένα email επαλήθευσης έχει σταλεί στα εισερχόμενά σας.', 'success')
                    else:
                        current_app.logger.info(f"Firebase verification link for {user.email}: {verify_link}")
                        flash('Ο λογαριασμός δημιουργήθηκε! Ο σύνδεσμος επαλήθευσης έχει καταγραφεί (ανάπτυξη).', 'success')
                else:
                    current_app.logger.warning(f"Could not generate Firebase verification link: {link_or_err}")
                    flash('Ο λογαριασμός δημιουργήθηκε. Παρακαλώ επαληθεύστε το email σας μέσω Firebase (ελέγξτε τα εισερχόμενά σας).', 'success')
            else:
                flash('Ο λογαριασμός δημιουργήθηκε. Παρακαλώ συνδεθείτε.', 'success')
        except Exception as e:
            current_app.logger.exception('Failed to generate Firebase verification link')
            flash('Ο λογαριασμός δημιουργήθηκε. Παρακαλώ συνδεθείτε.', 'success')

        return redirect(url_for('auth.login'))

    # render signup form
    return render_template('auth/signup.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        # Support login by username or email
        user = User.query.filter_by(username=identifier).first()
        if not user:
            user = User.query.filter_by(email=identifier).first()
        if not user or not user.check_password(password):
            flash('Μη έγκυρο όνομα χρήστη/email ή κωδικός πρόσβασης', 'error')
            return redirect(url_for('auth.login'))

        # Successful login: clear any previous active credential selection
        session.pop('active_credential', None)
        session.pop('_remote_qr_owner', None)

        login_user(user)
        # record last login
        try:
            user.last_login = datetime.datetime.utcnow()
            db.session.commit()
        except Exception:
            pass

        if not session.get('active_group'):
            user_groups = list(getattr(user, 'groups', []) or [])
            if len(user_groups) == 1:
                session['active_group'] = user_groups[0].name
                flash('Συνδεθήκατε επιτυχώς', 'success')
                return redirect(url_for('home'))
            else:
                if user_groups:
                    flash('Επίλεξε ενεργή ομάδα για να συνεχίσεις.', 'info')
                else:
                    flash('Δεν έχεις ακόμη αντιστοιχιστεί σε ομάδα. Επίλεξε ή δημιούργησε μία.', 'warning')
                return redirect(url_for('auth.list_groups'))

        flash('Συνδεθήκατε επιτυχώς', 'success')
        return redirect(request.args.get('next') or url_for('home'))

    # GET -> render login form
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    # if user has an active group, sync it to Firebase before clearing session
    try:
        active_group_name = session.get('active_group')
        if active_group_name:
            grp = Group.query.filter_by(name=active_group_name).first()
            if grp:
                # Cancel any idle timers for this user and run an immediate sync
                try:
                    firebase_config.firebase_cancel_idle_sync_for_user(current_user.id)
                except Exception:
                    pass
                try:
                    # First, push any local file changes back to Firebase
                    firebase_config.firebase_push_group_files(grp.data_folder)
                except Exception:
                    current_app.logger.exception('Failed to push files on logout')
                try:
                    firebase_config.firebase_sync_group_folder(grp.data_folder)
                except Exception:
                    current_app.logger.exception('Failed to sync data on logout')
    except Exception:
        # continue with logout even if sync fails
        pass

    logout_user()
    flash('Έχετε αποσυνδεθεί.', 'info')
    # clear any active client/credential selection and active group from session to avoid stale state
    session.pop('active_credential', None)
    session.pop('_remote_qr_owner', None)
    session.pop('active_group', None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/account', methods=['GET', 'POST'])
@login_required
def account_settings():
    if request.method == 'POST':
        current_password = request.form.get('current_password') or ''
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not current_password:
            flash('Συμπλήρωσε τον τρέχοντα κωδικό.', 'danger')
            return redirect(url_for('auth.account_settings'))

        if not new_password or not confirm_password:
            flash('Συμπλήρωσε τον νέο κωδικό και την επιβεβαίωση.', 'danger')
            return redirect(url_for('auth.account_settings'))

        if new_password != confirm_password:
            flash('Ο νέος κωδικός και η επιβεβαίωση δεν ταιριάζουν.', 'danger')
            return redirect(url_for('auth.account_settings'))

        if not current_user.check_password(current_password):
            flash('Ο τρέχων κωδικός δεν είναι σωστός.', 'danger')
            return redirect(url_for('auth.account_settings'))

        if len(new_password) < 8:
            flash('Ο νέος κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες.', 'warning')
            return redirect(url_for('auth.account_settings'))

        if current_password == new_password:
            flash('Ο νέος κωδικός πρέπει να είναι διαφορετικός από τον τρέχοντα.', 'warning')
            return redirect(url_for('auth.account_settings'))

        current_user.set_password(new_password)
        db.session.commit()
        flash('Ο κωδικός ενημερώθηκε με επιτυχία.', 'success')
        return redirect(url_for('auth.account_settings'))

    return render_template('auth/account.html')


@auth_bp.route('/groups', methods=['GET'])
@login_required
def list_groups():
    # Only show groups the current user belongs to or has been granted access to
    try:
        groups = current_user.groups
    except Exception:
        groups = []
    return render_template('auth/groups.html', groups=groups)


@auth_bp.route('/groups/assign-user', methods=['POST'])
@login_required
def assign_user_to_group():
    """Assign a user to a group by email or username (admin/group-admin only)"""
    try:
        group_name = (request.form.get('group_name') or '').strip()
        user_identifier = (request.form.get('user_identifier') or '').strip()  # email or username
        role = (request.form.get('role') or 'member').strip()
        
        if not group_name or not user_identifier:
            return jsonify({'ok': False, 'error': 'group_name and user_identifier required'}), 400
        
        grp = Group.query.filter_by(name=group_name).first()
        if not grp:
            return jsonify({'ok': False, 'error': 'group not found'}), 404
        
        # Check if current user is admin or group admin
        from admin_panel import is_admin
        if not (is_admin(current_user) or current_user.role_for_group(grp) == 'admin'):
            return jsonify({'ok': False, 'error': 'not authorized'}), 403
        
        # Find user by email or username
        user = User.query.filter_by(username=user_identifier).first()
        if not user:
            user = User.query.filter_by(email=user_identifier).first()
        
        if not user:
            return jsonify({'ok': False, 'error': f'user not found: {user_identifier}'}), 404
        
        # Add user to group with specified role
        user.add_to_group(grp, role=role)
        db.session.commit()
        
        return jsonify({'ok': True, 'message': f'User {user.username} assigned to {group_name} as {role}'})
    except Exception as e:
        current_app.logger.exception('Error assigning user to group')
        return jsonify({'ok': False, 'error': str(e)}), 500


@auth_bp.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    name = (request.form.get('name') or '').strip()
    data_folder = (request.form.get('data_folder') or '').strip()
    if not name or not data_folder:
        flash('Απαιτείται όνομα ομάδας και φάκελος δεδομένων', 'danger')
        return redirect(url_for('auth.list_groups'))

    if Group.query.filter_by(name=name).first():
        flash('Η ομάδα υπάρχει ήδη', 'warning')
        return redirect(url_for('auth.list_groups'))

    # sanitize folder name and validate uniqueness
    safe_folder = secure_filename(data_folder)
    if not safe_folder:
        flash('Μη έγκυρο όνομα φακέλου δεδομένων', 'danger')
        return redirect(url_for('auth.list_groups'))
    if Group.query.filter_by(data_folder=safe_folder).first():
        flash('Ο φάκελος δεδομένων χρησιμοποιείται ήδη από άλλη ομάδα', 'warning')
        return redirect(url_for('auth.list_groups'))

    # Enforce: a user may be admin in at most one group
    try:
        if getattr(current_user, 'is_authenticated', False):
            for ug in current_user.user_groups:
                if ug.role == 'admin':
                    flash('Είστε ήδη διαχειριστής σε άλλη ομάδα. Δεν μπορείτε να δημιουργήσετε άλλη.', 'danger')
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
    flash('Η ομάδα δημιουργήθηκε επιτυχώς', 'success')
    return redirect(url_for('auth.list_groups'))


@auth_bp.route('/groups/assign', methods=['POST'])
@login_required
def assign_user_to_group_legacy():
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
    Also attempts to ensure group data is available locally (lazy-pull from Firebase).
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

    # Attempt lazy-pull if group data missing locally
    try:
        import firebase_config
        if getattr(grp, 'data_folder', None):
            firebase_config.ensure_group_data_local(grp.data_folder)
    except Exception as e:
        # Log but don't fail - lazy-pull is non-critical
        current_app.logger.debug(f"Lazy-pull failed when selecting group {group_name}: {e}")

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


# =====================================================================
# Email Verification & Password Reset
# =====================================================================

@auth_bp.route('/verify-email', methods=['GET'])
def verify_email():
    """Verify user email via token link"""
    # When using Firebase Authentication, email verification is handled by Firebase.
    # The generated Firebase verification link will verify the user's email in Firebase.
    # Here we simply inform the user and, if possible, sync local user record.
    email = request.args.get('email')
    if email:
        try:
            # Try to sync verification status from Firebase
            from firebase_admin import auth as firebase_auth
            fb_user = firebase_auth.get_user_by_email(email)
            if fb_user and getattr(fb_user, 'email_verified', False):
                # Update local user record if present
                user = User.query.filter_by(email=email).first()
                if user:
                    user.email_verified = True
                    user.email_verified_at = datetime.datetime.utcnow()
                    db.session.commit()
                    flash('Το email επαληθεύτηκε επιτυχώς! Μπορείτε τώρα να συνδεθείτε.', 'success')
                    return redirect(url_for('auth.login'))
        except Exception:
            pass

    flash('Η επαλήθευση email διαχειρίζεται από το Firebase. Παρακαλώ ελέγξτε τα εισερχόμενά σας και ακολουθήστε τον σύνδεσμο που στάλθηκε από το Firebase για να επαληθεύσετε το email σας.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request password reset link"""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        if not email:
            flash('Απαιτείται το email', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
        try:
            # Use Firebase to generate password reset link and let Firebase handle sending.
            ok, link_or_err = FirebaseAuthHandler.generate_password_reset_link(email)
            if ok:
                reset_link = link_or_err
                # Enhanced email template for password reset
                app_url = os.getenv('APP_URL', 'http://localhost:5001')
                logo_url = f"{app_url}/icons/scanmydata_logo_3000w.png"
                html_body = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                            <div style="text-align: center; margin-bottom: 30px;">
                                <img src="{logo_url}" alt="ScanmyData" style="height: 60px; width: auto;">
                            </div>
                            <div style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                                <h1 style="margin: 0; font-size: 28px;">🔐 Επαναφορά Κωδικού</h1>
                            </div>
                            
                            <div style="background: white; padding: 30px; border: 1px solid #e1e5e9; border-radius: 0 0 10px 10px;">
                                <h2 style="color: #333; margin-top: 0;">Αλλαγή Κωδικού Πρόσβασης</h2>
                                <p style="color: #666; font-size: 16px; line-height: 1.6;">Λάβαμε αίτημα για επαναφορά του κωδικού πρόσβασής σας. Κάντε κλικ στο παρακάτω κουμπί για να ορίσετε νέο κωδικό:</p>
                                
                                <div style="text-align: center; margin: 30px 0;">
                                    <a href="{reset_link}" style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3);">🔑 Επαναφορά Κωδικού</a>
                                </div>
                                
                                <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0;">
                                    <p style="margin: 0; color: #856404; font-size: 14px;">⏰ <strong>Σημαντικό:</strong> Αυτός ο σύνδεσμος λήγει σε 1 ώρα για λόγους ασφαλείας.</p>
                                </div>
                                
                                <p style="color: #888; font-size: 14px; margin-top: 30px;">Εάν το κουμπί δεν λειτουργεί, αντιγράψτε αυτό το link:</p>
                                <p style="background: #f8f9fa; padding: 10px; border-radius: 5px; word-break: break-all; font-family: monospace; font-size: 12px;">{reset_link}</p>
                                
                                <hr style="border: none; height: 1px; background: #eee; margin: 30px 0;">
                                <p style="color: #888; font-size: 12px; text-align: center;">Εάν δεν ζητήσατε αυτή την αλλαγή, παραβλέψτε αυτό το email. Ο κωδικός σας θα παραμείνει αμετάβλητος.</p>
                                <div style="text-align: center; margin-top: 30px;">
                                    <img src="{logo_url}" alt="ScanmyData" style="height: 40px; width: auto; opacity: 0.6;">
                                </div>
                            </div>
                        </div>
                    </body>
                </html>
                """
                sent = email_utils.send_email(email, '🔐 Επαναφορά Κωδικού - ScanmyData', html_body)
                if sent:
                    flash('Εάν το email υπάρχει στο σύστημά μας, θα λάβετε σύνδεσμο επαναφοράς κωδικού (ελέγξτε τα εισερχόμενά σας).', 'info')
                else:
                    current_app.logger.info(f"Firebase password reset link for {email}: {reset_link}")
                    flash('Εάν το email υπάρχει στο σύστημά μας, θα λάβετε σύνδεσμο επαναφοράς κωδικού (ελέγξτε τα εισερχόμενά σας).', 'info')
            else:
                current_app.logger.warning(f"Could not generate Firebase password reset link: {link_or_err}")
                flash('Εάν το email υπάρχει στο σύστημά μας, θα λάβετε σύνδεσμο επαναφοράς κωδικού (ελέγξτε τα εισερχόμενά σας).', 'info')
            return redirect(url_for('auth.login'))
        except Exception as e:
            current_app.logger.exception('Forgot password failed')
            flash('Σφάλμα κατά την επεξεργασία του αιτήματος επαναφοράς κωδικού', 'danger')
            return redirect(url_for('auth.forgot_password'))
    
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password via token link"""
    # With Firebase-based flows, password reset is handled by Firebase links.
    # Users should follow the link sent by Firebase to reset their password.
    flash('Η επαναφορά κωδικού διαχειρίζεται από το Firebase. Παρακαλώ χρησιμοποιήστε τον σύνδεσμο που στάλθηκε στο email σας για να επαναφέρετε τον κωδικό σας.', 'info')
    return redirect(url_for('auth.login'))
