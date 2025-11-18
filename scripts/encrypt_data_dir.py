#!/usr/bin/env python3
"""Encrypt all files under data/ in-place using MASTER_ENCRYPTION_KEY.

WARNING: This will replace file contents with encrypted bytes. The application
must decrypt files before reading them. Run backups first.
"""
import os
import sys
import tempfile
from encryption import encrypt_file

BASE = os.path.join(os.getcwd(), 'data')
if not os.path.exists(BASE):
    print('No data/ directory found')
    sys.exit(1)

count = 0
for root, dirs, files in os.walk(BASE):
    for fname in files:
        full = os.path.join(root, fname)
        # skip our sync state
        if fname == '.firebase_sync_state.json':
            continue
        # write to temp file first
        fd, tmp = tempfile.mkstemp(dir=root)
        os.close(fd)
        ok = encrypt_file(full, tmp)
        if ok:
            try:
                # replace original with encrypted file
                os.replace(tmp, full)
                count += 1
                print('Encrypted:', full)
            except Exception as e:
                print('Failed replacing', full, e)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        else:
            try:
                os.remove(tmp)
            except Exception:
                pass

print(f'Done. Files encrypted: {count}')
