# Email Verification Guide (Firebase - Phase 1)

This project uses Firebase Authentication for email verification and password reset in Phase 1.
In Phase 2 we can switch to a custom SMTP-based flow managed by this server.

## Why Firebase for Phase 1
- Firebase provides battle-tested email verification and password reset flows.
- No SMTP setup required for development.
- Tokens, expiry and single-use behavior handled by Firebase.

## How it works in this repository
- Signup: `auth.signup` will attempt to register the user in Firebase (if enabled via `firebase_config`).
  - If registration succeeds, the local user record stores `firebase_uid`.
  - The server generates a Firebase email verification link via the Admin SDK and logs it for development.
  - In production the client SDK typically sends the verification email to the user.

- Password Reset: `auth.forgot-password` uses the Firebase Admin SDK to generate a password reset link and logs the link for development. Firebase handles the actual reset flow.

- Local fallback: If Firebase is not enabled, the code falls back to local-only user creation and (optionally) the earlier SMTP/token-based flows.

## Developer testing (no SMTP)

1. Enable Firebase in `firebase_config.py` (service account + database URL + FIREBASE_API_KEY env var).
2. Signup a new user via `/auth/signup`.
3. Check the Flask server logs - the generated verification link will be printed there.
4. Visit the generated link (it will lead to a Firebase action page which completes verification).
5. After the link, re-login to the app; the server may sync verification status from Firebase.

## How to generate links programmatically

This repo exposes helpers in `firebase_auth_handlers.py`:

- `FirebaseAuthHandler.generate_email_verification_link(email)` -> `(True, link)` or `(False, error)`
- `FirebaseAuthHandler.generate_password_reset_link(email)` -> `(True, link)` or `(False, error)`

These use the Admin SDK functions `firebase_auth.generate_email_verification_link` and `firebase_auth.generate_password_reset_link`.

## Phase 2: Custom SMTP (Optional)

In a later phase we will:
- Use `email_utils.py` to send emails via SMTP from this server.
- Use the existing token-based verification/reset (`VerificationToken` model) if we need custom behavior.
- Provide admin controls for email templates and sending.

## Notes / Caveats
- Firebase verification links and reset links are often intended to be handled by client-side code (web app) with a configured `continueUrl`. When using Admin SDK-generated links, the link can be visited directly and will complete the action.
- For production, ensure `APP_URL` and OAuth/continue URLs are configured in Firebase project settings if you want the flow to redirect back to your app.

## Example: development flow

```bash
# create user
curl -X POST -F "username=devuser@example.com" -F "password=devpass" http://localhost:5000/auth/signup
# Check server logs for generated verification URL
# Visit link in browser to verify
```

## Where to look in code
- `auth.py` - signup, forgot-password, verify-email, reset-password routes
- `firebase_auth_handlers.py` - Firebase helper methods (register_user, generate_*_link)
- `email_utils.py` - legacy SMTP/token helpers (Phase 2)

If you want, I can now:
- Remove the legacy token-based verify/reset routes altogether and fully switch to Firebase-only endpoints; or
- Add a small admin UI to copy generated Firebase links for manual sending/testing.
