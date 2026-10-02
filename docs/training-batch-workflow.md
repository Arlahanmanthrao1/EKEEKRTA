# Training institution batch workflow

Ekeekrta now separates a reusable **training program** from each dated **batch** that delivers it. University courses and semester workflows are unchanged.

## Roles

- **Administrator:** creates programs and batches, assigns a trainer, sets dates/capacity/certificate rules, enrolls learners individually or by CSV, and sees institution-wide training analytics.
- **Trainer:** sees only assigned batches, selects a folder from their own connected Google Drive, builds ordered modules and lessons, schedules or starts meetings, reviews attendance/progress, and generates eligible certificates.
- **Learner:** sees only batches where they have an explicit active/completed membership. The batch workspace contains published lessons, live/scheduled classes, progress, recordings when available, and issued certificates.

## CSV enrollment

Use a UTF-8 CSV up to 1 MB with either or both of these headers:

```csv
institutional_id,email
LEARNER-001,learner1@example.org
LEARNER-002,learner2@example.org
```

The learner account must already exist in the same institution and domain. The import reports added, already-enrolled, and rejected rows. It never creates duplicate accounts.

## Progress and certificates

Progress is calculated only from real stored records. Available categories are normalized using these weights:

- required published lessons: 40%
- assignment submissions in the program: 25%
- quiz attempts in the program: 20%
- present batch meeting sessions: 15%

A category with no records is excluded rather than fabricated. When the certificate attendance threshold is above zero, at least one batch meeting must have recorded attendance. A certificate becomes eligible only when the batch is completed and the configured progress and attendance thresholds are satisfied. Issued certificates have a unique certificate number and retain the eligibility snapshot used at issuance.

## Meetings and recordings

Scheduled classes and live sessions carry a `training_batch_id`. The server checks the assigned trainer or an explicit batch membership before granting meeting access or recording attendance. Training recordings use the selected batch folder and the assigned trainer's personal Google Drive connection. No public Drive fallback is used.

## Local verification

Starting the backend creates the new batch/module/lesson/certificate tables and adds the nullable batch link to class-session tables. Back up a shared database before the first start. The focused backend test is `tests/test_training_batches.py`; the frontend production build verifies the new routes and responsive workspace.
