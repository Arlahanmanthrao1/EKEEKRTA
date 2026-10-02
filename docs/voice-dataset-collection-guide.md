# EKEEKRTA Voice v1: pilot dataset collection guide

This guide creates the first English/Indian-English pilot dataset. It produces
3,000 clips when 30 consenting speakers each complete the 100-row recording
script. This pilot validates the training pipeline; it is not sufficient to
claim production speech-recognition quality.

## 1. Prepare governance before recording

1. Approve a written consent form covering recording, model training, storage,
   retention, withdrawal and deletion.
2. Store signed consent records outside the Git repository.
3. Assign each person a random ID (`SPK001` through `SPK030`) and a separate
   consent reference (`CONSENT-VOICE-0001`, etc.). Do not place names, email
   addresses, roll numbers or employee IDs in filenames or the manifest.
4. Assign every speaker to exactly one split before recording:
   - `SPK001`–`SPK021`: `train`
   - `SPK022`–`SPK025`: `validation`
   - `SPK026`–`SPK030`: `test`
5. Aim for a mixed group of students, faculty, HODs and administrators, with
   different accents, genders, speaking rates and microphone types.

Never move a speaker between splits. Re-recordings from the same person remain
in that person's original split.

## 2. Prepare the private directory

From the repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Force ".\private-ai-data\voice\audio" | Out-Null
Copy-Item ".\docs\voice-dataset-manifest.csv" ".\private-ai-data\voice\manifest.csv" -Force
```

Create one directory for each speaker, for example:

```text
private-ai-data/voice/
├── manifest.csv
└── audio/
    ├── SPK001/
    ├── SPK002/
    └── ...
```

`private-ai-data/` is excluded from Git. Do not remove that ignore rule and do
not upload raw recordings to GitHub.

## 3. Configure the recorder

Record or export every clip as:

- PCM WAV (not MP3 or renamed M4A)
- mono
- 16,000 Hz sample rate
- signed 16-bit PCM
- normally 1–15 seconds, never above 20 seconds

Disable automatic voice effects where possible. Do not use aggressive noise
removal, pitch correction or normalization. Keep the natural device and room
variation.

## 4. Record one speaker

1. Open [`voice-recording-script-v1.csv`](voice-recording-script-v1.csv).
2. Create that person's audio directory, such as `audio/SPK001/`.
3. Record one file for each prompt from `V001` through `V100`.
4. The person says only the text in the `text` column—not the prompt ID or the
   instruction.
5. Use a natural voice and accent. Do not imitate another accent.
6. If a sentence is spoken incorrectly, discard the entire clip and record it
   again.
7. Name each file `<speaker_id>_<prompt_id>.wav`, for example:
   `SPK001_V001.wav`.
8. Follow the special instruction instead of speaking for V096–V099. V100 is
   spoken from approximately two metres away.

Recommended variation per speaker:

- V001–V060: quiet room, microphone 30–50 cm away
- V061–V075: a fan or light constant room noise
- V076–V090: normal room or safe classroom ambience
- V091–V095: different microphone position or distance
- V096–V100: follow the row-specific acoustic instruction

Do not capture an identifiable private conversation in a background recording.

## 5. Add manifest rows

Add one row for every WAV file to
`private-ai-data/voice/manifest.csv`. Example:

```csv
sample_id,audio_path,transcript,language,speaker_id,role,device,noise_condition,consent_id,recorded_at,split
SPK001_V001,audio/SPK001/SPK001_V001.wav,Schedule a class for Cloud Computing tomorrow at ten AM,en-IN,SPK001,faculty,Windows laptop built-in microphone,quiet,CONSENT-VOICE-0001,2026-09-25T10:30:00+05:30,train
```

Rules:

- `sample_id`: `<speaker_id>_<prompt_id>` and globally unique.
- `audio_path`: relative to `private-ai-data/voice/`, using `/` separators.
- `transcript`: exact script text, including numbers and course codes.
- `language`: `en-IN` for this pilot.
- `role`: `student`, `faculty`, `hod` or `admin` for the speaker/persona.
- `device`: a general description only; never include a serial number.
- `noise_condition`: normally `quiet`, `fan`, `classroom`, `far_microphone`,
  `silence`, `background_noise` or `unknown_speech`.
- `consent_id`: reference to the separately stored signed consent.
- `recorded_at`: ISO date and time including time-zone offset.
- `split`: the split assigned to the speaker in step 1.

For V096–V099, leave `transcript` empty and use the matching non-speech
condition: `silence`, `background_noise` or `unknown_speech`.

The role in the recording script is the intended application role for that
command. The manifest role records the role/persona assigned to the speaker.

## 6. Review recordings

Have a second authorized reviewer check every clip with headphones:

- the file contains exactly one requested utterance;
- the manifest transcript matches the spoken words;
- the beginning or end is not cut off;
- speech is understandable and not clipped;
- no personal or confidential information is audible;
- the sample is not duplicated;
- the audio genuinely came from the recorded speaker.

Mark failed clips for re-recording. Do not repair an incorrect transcript to
hide a recording error.

## 7. Run structural validation

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe .\backend\scripts\validate_voice_dataset.py --dataset ".\private-ai-data\voice"
```

If the virtual environment is unavailable, activate or recreate the backend
environment first. A successful result ends with:

```text
Dataset structure passed validation.
```

Validation checks WAV format, duration, paths, required metadata, duplicate
sample IDs and speaker leakage across splits. It does not replace consent or
human audio review.

## 8. Freeze the pilot dataset

After validation:

1. Stop editing the accepted copy.
2. Assign a dataset version such as `ekeekrta-voice-pilot-v1`.
3. Calculate and retain file checksums in the private storage system.
4. Record the dataset sources, licences, consent version and review date.
5. Keep an untouched test split; never train or tune using its recordings.
6. Back up the encrypted private dataset to access-controlled institutional
   storage—not GitHub or a public Drive folder.

## 9. Pilot acceptance target

The completed pilot should contain:

- 30 speakers
- 100 clips per speaker
- 3,000 total clips
- approximately 21 training, 4 validation and 5 test speakers
- at least 20% device/noise variation
- at least 10% unsupported or non-command examples

Only after this pilot passes ingestion, training and held-out evaluation should
collection expand toward the production target in
[`voice-dataset-spec.md`](voice-dataset-spec.md).
