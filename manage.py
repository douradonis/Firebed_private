#!/usr/bin/env python3
"""
Simple manage script to create initial users/groups.
Usage:
  python manage.py create-admin --username admin --password secret
  python manage.py create-group --name demo --folder client_demo

This script requires the packages in requirements.txt (Flask-SQLAlchemy, Flask-Login).
"""
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    a = sub.add_parser('create-admin')
    a.add_argument('--username', required=True)
    a.add_argument('--password', required=True)

    g = sub.add_parser('create-group')
    g.add_argument('--name', required=True)
    g.add_argument('--folder', required=True)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    # Import app and models lazily
    from app import app
    try:
        from models import db, User, Group
    except Exception as e:
        print('Failed to import models (missing deps?):', e)
        sys.exit(2)

    with app.app_context():
        db.create_all()
        if args.cmd == 'create-admin':
            if User.query.filter_by(username=args.username).first():
                print('User exists')
                return
            u = User(username=args.username)
            u.set_password(args.password)
            db.session.add(u)
            db.session.commit()
            print('Admin user created')
        elif args.cmd == 'create-group':
            if Group.query.filter_by(name=args.name).first():
                print('Group exists')
                return
            g = Group(name=args.name, data_folder=args.folder)
            db.session.add(g)
            db.session.commit()
            print('Group created')

if __name__ == '__main__':
    main()
