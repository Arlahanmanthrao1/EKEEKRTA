# Ekeekrta platform operations

The Ekeekrta operator portal is separate from every university or training-institution portal. Institution administrators cannot list or manage other institutions, and platform operators do not belong to an institution tenant.

## What the portal provides

- A platform summary with institution, user, and course counts.
- A review queue for newly registered institutions.
- Filters for universities, training institutions, and account status.
- Approval, suspension, rejection, and reactivation controls.
- Immediate session revocation when an institution is suspended or rejected.
- An immutable operator audit trail containing the operator, institution, status change, reason, and time.
- No access to passwords, API tokens, assignment submissions, marks, meetings, or other tenant academic data.

New institution registrations begin in `pending` status. Their administrator cannot sign in until an Ekeekrta operator approves the institution. Existing institutions are migrated to `active`, preserving their current access.

## Create the first platform operator

1. Deploy the backend schema update first, or start the updated backend once against the database.
2. In Neon, open the same project used by the deployed Ekeekrta backend and copy its PostgreSQL connection string.
3. In a local PowerShell window, go to the `backend` folder and run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\create_platform_admin.py --email your-team-email@example.org --clipboard
   ```

4. When prompted, copy the Neon connection string, return to PowerShell, and press Enter. The script reads it from the clipboard without printing it.
5. Choose a unique password of at least 12 characters and type `CREATE` when asked.
6. Sign in at `/platform-login`; on the public site this is `https://ekeekrta.vercel.app/platform-login`.

The script refuses to promote or overwrite an existing user. Platform operators can only sign in on the main Ekeekrta address, never through an institution-specific login address.

## Institution status behavior

| Status | Institution access |
| --- | --- |
| Pending | Login blocked until reviewed |
| Active | Normal institution access |
| Suspended | Login and authenticated requests blocked; existing sessions revoked |
| Rejected | Login and authenticated requests blocked; existing sessions revoked |

Suspending and rejecting require a review reason. Reactivating an institution does not restore old revoked tokens; users sign in again.
