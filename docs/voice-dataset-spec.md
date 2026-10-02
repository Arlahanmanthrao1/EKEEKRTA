# EKEEKRTA Voice v1 dataset specification

EKEEKRTA Voice v1 will be trained from scratch for education-platform commands.
It will not download or fine-tune an external speech model. The application
pipeline is already present; model training starts only after a reviewed dataset
passes this specification.

## Initial scope

The first release is English-first and must recognize natural commands for
students, faculty, HODs and administrators. It must preserve course names/codes,
department names, dates, times, assessment topics and numbers accurately. Every
write remains a preview requiring visual confirmation.

## Audio requirements

- PCM WAV, mono, 16 kHz, signed 16-bit little-endian.
- One utterance per file, normally 1–15 seconds and never over 20 seconds.
- Natural volume without clipping, long leading silence or aggressive denoising.
- Real variation: laptop/mobile microphones, quiet rooms, fans, classroom noise,
  distance from microphone and ordinary speaking rates.
- Do not include names, IDs, grades, passwords, tokens or private conversations.

## Manifest

Copy the header-only [`voice-dataset-manifest.csv`](voice-dataset-manifest.csv).
Use one row per WAV file:

| Field | Rule |
|---|---|
| `sample_id` | Unique non-identifying ID |
| `audio_path` | Relative path below the private dataset directory |
| `transcript` | Exact words spoken, including course codes and numbers |
| `language` | BCP-47 tag; use `en-IN` for Indian English |
| `speaker_id` | Random pseudonymous ID; never a name, email or roll number |
| `role` | `student`, `faculty`, `hod` or `admin` |
| `device` | General category/model, without a device serial number |
| `noise_condition` | `quiet`, `fan`, `classroom`, `outdoor` or another reviewed label |
| `consent_id` | Reference to the institution-held consent record, not the consent text |
| `recorded_at` | ISO date/time |
| `split` | `train`, `validation` or `test` |

One speaker may occur in only one split. Near-duplicate recordings and sessions
must also remain within one split.

## Quantity needed

For a credible limited-domain first release, provide:

- At least 300 consenting speakers covering intended accents and speaking styles.
- At least 200 hours of reviewed speech; 300–500 hours is preferred.
- Approximately 60,000–150,000 short utterances.
- A speaker-disjoint 70% training, 15% validation and 15% test allocation.
- At least 20% noisy/device-varied recordings.
- At least 10% negative examples: silence, unrelated speech and unsupported
  requests, all labelled accurately.

A smaller pilot of 30 speakers and 3,000–5,000 clips can validate the pipeline,
but must not be called a production voice model.

## Prompt coverage

For the 30-speaker pilot, use
[`voice-recording-script-v1.csv`](voice-recording-script-v1.csv). Each speaker
records all 100 rows as separate clips. Rows V096-V099 are acoustic negatives;
their transcript field remains empty and `noise_condition` must be `silence`,
`background_noise` or `unknown_speech`. Follow the complete
[`voice-dataset-collection-guide.md`](voice-dataset-collection-guide.md). Do not
replace the example course names with real student or staff information.

Record paraphrases for every supported intent, plus entity-rich variations:

- Schedule/reschedule a class with course, date and time.
- Create assignment and quiz drafts with course, topic, marks and question count.
- Ask for attendance, marks, progress, risks and CGPA planning.
- Create departments/courses and open bulk-account or ERP workflows.
- Ask course questions using approved knowledge sources.
- Help, cancellation, correction and explicit confirmation/refusal wording.

Include similarly worded commands with different meanings so evaluation measures
real discrimination rather than memorization. Never record real credentials.

## Consent and storage

The institution must retain the signed consent separately, define deletion and
retention periods, and provide a withdrawal process. Audio and manifests belong
under `private-ai-data/`, which is excluded from Git. Only authorized model
operators may access it.

## Acceptance gate

The held-out test report must include word error rate, course/entity accuracy,
intent accuracy, false activation rate, rejection accuracy, latency and results
by accent/noise/device group. The model stays disabled if any institution-set
threshold fails or if confidence is not calibrated.
