#!/usr/bin/env python3
from app import app
from models import db, Group

with app.app_context():
    groups = Group.query.all()
    for g in groups:
        print(f'Group: {g.name}, data_folder: {g.data_folder}')