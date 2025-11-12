from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


class UserGroup(db.Model):
    __tablename__ = 'user_group'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), primary_key=True)
    role = db.Column(db.String(32), nullable=False, default='member')

    user = db.relationship('User', back_populates='user_groups')
    group = db.relationship('Group', back_populates='user_groups')


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    user_groups = db.relationship('UserGroup', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def groups(self):
        return [ug.group for ug in self.user_groups]

    def add_to_group(self, group, role='member'):
        # replace existing role if present
        for ug in self.user_groups:
            if ug.group_id == group.id:
                ug.role = role
                return
        ug = UserGroup(user=self, group=group, role=role)
        self.user_groups.append(ug)

    def role_for_group(self, group):
        for ug in self.user_groups:
            if ug.group_id == group.id:
                return ug.role
        return None


class Group(db.Model):
    __tablename__ = 'group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    # filesystem-relative folder under data/ this group can access
    data_folder = db.Column(db.String(255), nullable=False, default='')

    user_groups = db.relationship('UserGroup', back_populates='group', cascade='all, delete-orphan')

    def users(self):
        return [ug.user for ug in self.user_groups]

    def admins(self):
        return [ug.user for ug in self.user_groups if ug.role == 'admin']

    def __repr__(self):
        return f"<Group {self.name} -> {self.data_folder}>"
