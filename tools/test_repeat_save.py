# test_repeat_save.py
# Run inside the workspace to exercise /api/repeat_entry/save using Flask test client
from app import app
import json

username = 'douradonis'
password = '123'
group = 'douradonis'
credential_name = 'ΒΑΨΙΜΟ'
vat = '802576637'

mapping = {
    '0%': 'δαπανες_χωρις_φπα',
    '6%': 'αγορες_α_υλων',
    '13%': 'αγορες_α_υλων',
    '17%': 'γενικες_δαπανες',
    '24%': 'αγορες_α_υλων'
}

with app.test_client() as client:
    # Login via API
    resp = client.post('/api/login', json={'username': username, 'password': password})
    print('login status:', resp.status_code, resp.get_data(as_text=True))

    # Select group
    resp = client.post('/groups/select', data={'group': group})
    print('select_group status:', resp.status_code, resp.get_data(as_text=True))

    # Set active credential (form route)
    resp = client.post('/set_active', data={'active_name': credential_name}, follow_redirects=True)
    print('set_active status:', resp.status_code)

    # Save repeat entry
    payload = {
        'enabled': True,
        'mapping': mapping,
        'vat': vat
    }
    resp = client.post('/api/repeat_entry/save', json=payload)
    print('save_repeat status:', resp.status_code)
    try:
        print('save_repeat body:', resp.get_json())
    except Exception:
        print('save_repeat raw:', resp.get_data(as_text=True))

    # Read the group credentials file to verify persistence
    import os
    creds_path = os.path.join(app.root_path, 'data', group, 'credentials.json')
    if os.path.exists(creds_path):
        try:
            with open(creds_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print('\ncredentials.json entries:')
            for c in data:
                if str(c.get('vat','')).strip() == vat:
                    print(json.dumps(c, ensure_ascii=False, indent=2))
        except Exception as e:
            print('Failed reading credentials file:', e)
    else:
        print('credentials file not found at', creds_path)
