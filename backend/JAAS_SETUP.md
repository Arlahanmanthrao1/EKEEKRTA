# JaaS Dev setup

The LMS now defaults to JaaS. Meetings will show a setup error until your real
credentials are configured; there is no silent fallback to public Jitsi.
No subscription purchase or account creation is performed by this project.

## Account and credentials

1. Sign up at https://jaas.8x8.vc/ and select the free **Dev** offering.
   Check the current allowance in your console: the documented free tier is
   25 monthly active users/endpoints across the account, not per class.
   Teachers and different devices/browsers can count too. Do not upgrade or
   enable billable add-ons unless you intend to pay.
2. In **API keys**, add a generated key pair. Download the private key before
   closing the dialog. Save your App ID and the full API Key ID (including the
   App ID prefix). See https://developer.8x8.com/jaas/docs/jaas-console-api-keys/.
3. Store the downloaded private key outside the repository/OneDrive if possible,
   in a folder accessible only to your Windows account. Do not paste it in chat,
   commit it, or put it in a frontend environment variable.

## Backend configuration

Edit your existing `backend/.env` and add these values, preserving your current
database and authentication settings. Replace the descriptive placeholders with
your own credentials; they are not working credentials:

```dotenv
VIDEO_PROVIDER=jaas
JAAS_APP_ID=your-full-app-id
JAAS_API_KEY_ID=your-full-app-id/your-key-id
JAAS_PRIVATE_KEY_PATH=C:/absolute/path/outside-the-repository/jaas-private.pem
JAAS_TOKEN_EXPIRE_MINUTES=60
```

Restart the backend from the `backend` folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Run `npm run dev` from `frontend` and reload the browser. `VITE_JITSI_DOMAIN`
is no longer used: the backend supplies the domain and App-ID-specific script.
Never put the private key in a `VITE_` variable.

## Verify with real users

1. Sign in as a faculty member and start a class in a course they own.
2. In another browser/private window, sign in as a real enrolled student and
   join that same course's live session. Separate browser profiles prevent the
   two LMS logins overwriting each other.
3. Confirm both people appear in one meeting, test audio/video and a call longer
   than five minutes, then test fullscreen policy and ending the class.
4. Check the student's recorded attendance and JaaS console Activity usage.
   A live call has not been verified until these steps succeed with your account.

The backend signs a separate RS256 token for each authorized participant. Tokens
are scoped to the stored class room, expire after 60 minutes by default, and are
not cached. This expiration is the join-token validity, not a configured meeting
duration. Reload the classroom to request a fresh token when rejoining later.
Only the owning faculty or an admin gets moderator permissions. Recording,
transcription, livestreaming and telephone features are disabled in the tokens.
The browser sends the authenticated user's display name and ID to JaaS, along
with the media required for the call; no email is included in our meeting token.
The ID is the permanent EKEEKRTA database user ID, so creating a new class or a
new join token does not create a new application identity for that student.

JaaS MAU billing is different from this application identity. JaaS identifies a
MAU using an identifier stored locally by JaaS on the meeting device/browser.
Repeated classes in the same month on the same browser/device do not normally
create another MAU while that storage remains available. A different device,
browser profile or private session, clearing site data, or removing the JaaS app
can produce another device identifier and therefore another MAU. EKEEKRTA cannot
force JaaS to bill multiple devices as one MAU merely by reusing the JWT user ID.
See https://developer.8x8.com/jaas/docs/faq/ and confirm actual usage in the JaaS
Console Activity page.

## Limits and future college hosting

Dev is for small tests, not 150 students per class. Track the whole account's
monthly usage: https://developer.8x8.com/jaas/docs/faq/.

For a future college Jitsi installation, the connection supports
`VIDEO_PROVIDER=jitsi` and `JITSI_DOMAIN=meet.your-college-domain`.
This mode is the unauthenticated iframe integration; secure college-hosted JWT
authentication, infrastructure configuration and load testing remain separate
deployment work. It does not inherit JaaS token security automatically.

## Local verification without using JaaS quota

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Tests create only in-memory records and keys, never seed or reset the real LMS
database, and never connect to JaaS.
