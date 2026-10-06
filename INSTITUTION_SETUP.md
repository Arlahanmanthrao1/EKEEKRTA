# Institution onboarding and access

The current public portal is <https://ekeekrta.vercel.app/login>. Institution onboarding is implemented, but public self-service registration still requires stronger ownership verification and abuse controls before real institutional use. Custom institution domains are optional and must be verified and configured by the platform operator.

## Workflow

1. On the login page, choose **Register your institution**.
2. Enter the institution name, official email, optional hosted HTTPS logo URL and address.
3. Create its first administrator with an email on the same domain and a password of at least 12 characters.
4. Sign in as that administrator. Create departments on **Departments**.
5. Use **Create HOD**, **Create faculty**, and **Register student**, assigning a department to each account.
6. Use **Users → Edit account** to correct names and department assignments. Account roles and institution ownership cannot be injected through this form/API.
7. Use **Institution profile** to update contact details and logo. Institution name/logo appear in the dashboard header.

There is no public student/staff registration. Administrator-created credentials must be shared privately; no credentials email is sent.

| Role | Visibility and authority |
| --- | --- |
| Administrator | All accounts and courses in their institution; institution details, departments, account creation and account details management. |
| HOD | Read-only faculty, students, courses and attendance within their assigned department. No account creation, grading or classroom moderator controls. No department means no directory/course results. |
| Faculty | Their own courses and students currently enrolled in those courses. Attendance summaries exclude other faculty members’ courses. |
| Student | Own records and enrolled coursework. Can browse and enroll in courses only within their institution. |

These limits are enforced on the server, including guessed resource IDs, grades, quizzes, materials, meeting tokens and attendance. Departments with the same name in different institutions are separate. Course codes may repeat across institutions but not within one institution.

## Existing HITAM records

The user confirmed HITAM and `hitam.org` as the legacy owner. A complete official contact email was not provided; it is left empty until an administrator supplies one.

The local SQLite database was backed up and migrated. Two accounts and three courses were assigned to HITAM without replacing credentials or identities. Local backup (keep private):

`backend/lms-before-institutions-20260904T145016Z-de90a6a6.db`

The local copy has one faculty account and one student account, **no administrator**. No account was promoted. To create a new first administrator, run from `backend/` after checking that the configured database is the intended local database:

```powershell
.\.venv\Scripts\python.exe -B scripts/create_institution_admin.py --domain hitam.org --email YOUR-REAL-ADMIN-EMAIL@hitam.org
```

Replace the placeholder with a real unused email address. The command asks for name, a hidden password and explicit `CREATE` confirmation. It refuses to replace an account or create another administrator when this institution already has one. The older `create_first_admin.py` is for the pre-institution database only.

## Existing hosted database: deployment gate

Do not deploy this backend over an unmigrated database. Startup deliberately refuses the old schema. This release uses an explicit upgrade script, not Alembic.

1. Back up Neon using its supported backup/restore workflow; confirm the intended branch/database. Stop application writes during migration. Never paste the connection string into chat or commit it.
2. Configure `DATABASE_URL` privately for the target database in the terminal/environment running the script. Preview from `backend/`:

   ```powershell
   .\.venv\Scripts\python.exe -B scripts/migrate_institutions.py --name HITAM --domain hitam.org
   ```

3. Review counts and ownership. The preview makes no changes. Once the backup is confirmed, apply:

   ```powershell
   .\.venv\Scripts\python.exe -B scripts/migrate_institutions.py --name HITAM --domain hitam.org --apply --backup-confirmed
   ```

   Optionally add `--email` with HITAM’s actual official contact email. No website address or bare `@hitam.org` is accepted as an email.

4. The PostgreSQL upgrade runs within a transaction. SQLite rebuilds the course table to replace the global course-code uniqueness rule while retaining IDs and relationships; custom columns/indexes/triggers require review instead of being discarded. Existing account passwords and academic records are preserved.
5. Verify institution assignment, administrator login and role isolation on the target database. The 4 September production upgrade was rehearsed against a restored PostgreSQL 18 database before application to Neon; SQLite regression tests also remain available.
6. Deploy the backend and frontend together through the existing Vercel projects. Keep the backup and verify real role workflows before resuming writes. Reverting application code alone is not a database rollback.

## Boundaries and remaining work

- Public institution registration is **self-service and unverified**. No email/DNS ownership verification, approval queue, CAPTCHA or onboarding rate limit is implemented. Add those safeguards before opening registration to arbitrary institutions in production; reserving a domain here is not proof of institutional ownership.
- One institution per email domain and globally unique account emails. Multiple institutions sharing the same domain are not supported yet.
- Logo input accepts a hosted HTTPS image URL, not file upload. Remote images are rendered by the browser with no referrer; the backend never fetches arbitrary logo URLs.
- ERP connections are configured per university institution. Training institutions do not expose ERP controls. Each connector has its own HTTPS base URL, institution ID, encrypted token, selected sync directions and delivery ledger.
- JaaS credentials are still deployment-wide; API membership checks restrict tokens to authorized rooms. This phase does not change provider capacity, plans or hosting.
- EKEEKRTA branding is implemented locally; see BRANDING.md. Institution names and logos remain separate.
- Tests contain isolated fixtures only. No dummy institutions, accounts or academic activity are seeded into application databases.

## Verification

Latest local result before custom-domain work: 56 backend tests passed; 26 dashboard routes and new form-rendering checks passed; frontend production build passed. The migrated local backend returned HTTP 200 for health and HTTP 401 for an unauthenticated directory request. Custom-domain verification is recorded in project_details.txt.

From `backend/`: ` .\.venv\Scripts\python.exe -B -m unittest discover -s tests -q`

From `frontend/`: `node tests/dashboard-pages.cjs` and `npm run build -- --outDir .jaas-build-check`.

Automated checks cover onboarding rollback, scoped reads/writes, HOD restrictions, faculty roster/attendance boundaries, quiz answer safety, meeting permissions, migration preservation and ERP separation. Browser interaction testing and a live multi-institution production audit have not been performed in this phase.

## Institution login addresses — local support, not publicly connected

Chosen pattern: `https://ekeekrta.<institution-email-domain>/login`. For HITAM,
the intended address is `https://ekeekrta.hitam.org/login`. This is a subdomain
of HITAM's existing domain, not a new domain created by registering an institution.

The login page reads its hostname and requests the corresponding institution's
real name, logo and email domain. It does not use placeholder college data.
Unknown or unconfigured institution hosts show an error and no sign-in form.
The main site retains generic login and institution registration. Institution
portals hide and reject new-institution registration; students and staff still
receive accounts from their administrator.

### Operator configuration

`INSTITUTION_LOGIN_HOSTS` is a JSON object in backend environment settings,
defaulting to `{}`. After independently reviewing domain ownership AND the
institution/admin records, an operator can configure:

```dotenv
INSTITUTION_LOGIN_HOSTS={"ekeekrta.hitam.org":"hitam.org"}
```

This example is **not enabled** in the local private environment or on Vercel.
Use the actual registered email domain; it is not the institution display name.
Each key must be lowercase `ekeekrta.<domain>` without a scheme, slash, port,
underscore or wildcard. Multiple institutions require separate explicit entries.
Only the platform operator can change this configuration; self-service
registration never activates a custom domain. No schema migration is needed for
this mapping (the earlier multi-institution migration is still required).

Configured hosts are added to the backend's exact HTTPS CORS allowlist. Keep
`ALLOWED_ORIGINS` for the main frontend. Restart/redeploy the backend after changing
the mapping. The frontend continues using its existing `VITE_API_BASE_URL`.

Host context is checked at login and on authenticated requests, in addition to
existing institution/role permissions. Custom-portal JWTs are bound to that host;
tokens aren't transferred through URLs or shared across origins. A conflicting
Origin/header is rejected. Host routing is not authentication: user credentials
and stored institution membership remain authoritative. Public branding exposes
no account list, contact email or address.

### Connecting it publicly later (not performed)

First complete the hosted-database migration and deployment gate above. Then:

1. Obtain approval from HITAM's domain administrator and review the HITAM tenant
   and administrator ownership. Self-service registration is not proof of either.
2. In the **frontend** Vercel project, open Settings → Domains and add
   `ekeekrta.hitam.org` (no `https://` or `/login`).
3. Ask HITAM's DNS administrator to add the exact CNAME record Vercel displays,
   plus any requested verification record. Do not guess a CNAME target, change
   nameservers, or replace the existing `moodle.hitam.org`/mail records.
4. Wait for Vercel to confirm domain configuration and HTTPS readiness. Enable
   the reviewed backend mapping above and deploy both updated applications.
5. Check that `/login` displays the real HITAM profile and test institution/role
   isolation with authorized accounts. Sign in separately on each origin.

The admin Institution Profile page displays the intended address and whether it
is configured in EKEEKRTA. This is **not** a DNS/HTTPS availability check.
Official instructions: [Vercel custom domains](https://vercel.com/docs/domains/working-with-domains/add-a-domain).

No domain was purchased or DNS changed. The support code was deployed to the
existing Vercel site after the verified Neon upgrade on 4 September 2026.
Interactive custom-domain verification awaits an authorized test domain.

## Production release record — 4 September 2026, approximately 22:06 IST

- Frontend: `dpl_4TfRiSdV2cRHBsRnbJB8HgMNLhgJ`.
- Backend: `dpl_2ZVAWr9aEZdueqAJ42bcuTKBPFwD`.
- Neon: six accounts (one admin, one faculty, four students), one course;
  existing credentials and all pre-existing table records verified unchanged
  apart from intended institution assignment/department normalization.
- Verified backup: `C:/Users/arlah/ekeekrta-backups/deploy-20260904-3a1be3c346e34f208c1a04970d916fbc/before-institutions.dump`.
  Adjacent `verified-backup.json` records checksums and successful restore/migration
  rehearsal. This directory is private and outside the repository/OneDrive.
  Keep it confidential: backups contain account and academic data.
- An isolated local PostgreSQL 18 server was used for full restore and migration
  rehearsal, then stopped. Timestamp comparisons normalize to UTC so Windows and
  Neon timezone settings do not cause false record-change alarms.
- The public backend was put into maintenance mode for the migration. A write
  lock and backup comparison guarded the transaction. It now serves the new API.
- Verified public checks: frontend branding and backend URL; API health 200;
  unauthenticated profile routes 401; docs 404; expected frontend CORS accepted;
  unconfigured HITAM custom portal rejected. Interactive account login and video
  calls have not been tested in the browser after deployment.
- Existing passwords, JaaS settings and Vercel environment secrets were not reset.
  GitHub was not pushed and automatic Git deployments remain disconnected.
- Do not roll back application code alone: the older backend lacks institution
  isolation. Restore planning must account for any records added after release.
