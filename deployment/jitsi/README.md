# EKEEKRTA Stage 4: private Jitsi/Jibri deployment

This directory documents the connection contract; it does not vendor or modify
Jitsi. Download a tagged stable release of the official
[`docker-jitsi-meet`](https://github.com/jitsi/docker-jitsi-meet/releases)
package as required by the official
[Docker self-hosting guide](https://jitsi.github.io/handbook/docs/devops-guide/devops-guide-docker/).
Do not deploy the repository's empty legacy root `docker-compose.yml`.

## Required production topology

- A public DNS name such as `meet.institution.edu` with a valid HTTPS certificate.
- Jitsi web, Prosody, Jicofo and at least one JVB from the official package.
- JWT authentication with anonymous fallback disabled and a reviewed
  `token_affiliation` Prosody module. EKEEKRTA is the only JWT issuer; it signs
  `owner` only for an authorized faculty/admin manager and `member` for students.
  Test role behavior on the exact stable release before production; plain JWT
  authentication alone is not sufficient to enforce EKEEKRTA moderator roles.
- A Jibri machine or container with at least 2 GB shared memory and writable
  private storage. One Jibri handles one simultaneous recording, so concurrent
  recorded classes require a pool and real load testing.
- A separate EKEEKRTA worker with access to the finalized Jibri storage,
  database and private recording directory. Never put these videos in Vercel.

## Jitsi environment alignment

Copy the official package's `env.example` to `.env`, run its official
`gen-passwords.sh`, and then review at least these values. Generate unique
secrets; never copy the placeholders below into a live server.

```dotenv
PUBLIC_URL=https://meet.institution.edu
ENABLE_AUTH=1
AUTH_TYPE=jwt
JWT_APP_ID=replace-with-random-app-id
JWT_APP_SECRET=replace-with-a-long-random-secret
JWT_ALLOW_EMPTY=0
JWT_TOKEN_AUTH_MODULE=token_affiliation
ENABLE_RECORDING=1
JIBRI_RECORDING_DIR=/storage/recordings
JIBRI_FINALIZE_RECORDING_SCRIPT_PATH=/config/finalize.sh
```

Start the official stack with its Jibri override as documented by that release.
The exact compose files and directory layout belong to the downloaded stable
package, not this application repository.

## Matching EKEEKRTA backend configuration

```dotenv
VIDEO_PROVIDER=jitsi
JITSI_DOMAIN=meet.institution.edu
JITSI_JWT_APP_ID=replace-with-the-same-app-id
JITSI_JWT_APP_SECRET=replace-with-the-same-secret
JITSI_AUTO_RECORDING_ENABLED=true
JIBRI_RECORDINGS_DIR=/srv/jitsi-recordings
RECORDING_STORAGE_DIR=/srv/ekeekrta-private-recordings
NATIVE_SPEECH_MODEL_EXECUTABLE=/opt/ekeekrta-models/stt
NATIVE_SPEECH_MODEL_ID=ekeekrta-stt-v1
NATIVE_SLIDE_OCR_EXECUTABLE=/opt/ekeekrta-models/slide-ocr
NATIVE_SLIDE_OCR_MODEL_ID=ekeekrta-slide-ocr-v1
```

`JITSI_AUTO_RECORDING_ENABLED` must remain false until Jibri actually works.
The iframe waits for the server-confirmed moderator role, starts file recording,
shows real recording status, and stops recording before faculty ends the class.

## Finalized recording handoff

Jitsi receives `ekeekrta_session_id` as recording metadata. On the private host,
import a finalized directory (or invoke this command from a reviewed host-side
finalizer/watcher):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\import_jibri_recording.py `
  --recording-directory "C:\private\jibri\recording-directory" `
  --permissions-confirmed
```

The importer accepts only a child of `JIBRI_RECORDINGS_DIR`, exactly one MP4 or
WebM, a completed EKEEKRTA session and confirmed institutional permission. It
copies the file to opaque private storage and queues the processing worker:

```powershell
.\.venv\Scripts\python.exe scripts\run_recording_worker.py --max-jobs 10
```

If Jibri does not retain the custom metadata in its JSON, pass the authenticated
EKEEKRTA session explicitly with `--session-id`. Do not infer it from a display
name or accept it from a public browser callback.

## Not optional before a real class

Verify DNS, HTTPS, JWT rejection, firewall rules (including the JVB media port),
NAT/CGNAT, recording consent, retention/deletion policy, disk monitoring and
backups. Run two-person tests from separate networks, then staged load tests.
The current laptop has no running Docker engine and no FFmpeg installation, so
this repository has not performed a real call or recording test.
