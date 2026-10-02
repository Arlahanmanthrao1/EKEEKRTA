# EKEEKRTA private voice-command model contract

Voice control never uses browser speech recognition or a cloud inference API.
The institution installs a reviewed executable and immutable model ID on the
private backend/worker. Audio is accepted only after an authenticated user
presses the microphone button and is deleted immediately after inference.

## Executable invocation

```text
<voice-executable> --input-audio <private-audio-path> --output-json <temporary-json>
```

The executable must accept WAV, WebM/Opus, OGG or MP4 audio produced by supported
browsers, or safely reject formats it cannot decode. It must write:

```json
{
  "schema_version": 1,
  "language": "en",
  "confidence": 0.91,
  "text": "Schedule Cloud Computing tomorrow at 10:30 AM"
}
```

The backend accepts 3–2,000 normalized characters and confidence from 0 to 1.
Invalid, missing or oversized JSON fails closed. Output below
`NATIVE_VOICE_MIN_CONFIDENCE` is rejected and never becomes an action.

## Product safety boundary

Recognized text is passed through the existing role, institution, department,
course and student authorization checks. A write action becomes a preview and
the requesting user must confirm it visually. Voice never confirms an action,
changes a role or bypasses authorization. The raw audio is not retained and the
audit log stores model metadata rather than audio.

## Dataset and evaluation

Collect only consented short commands with transcripts, language, accent,
device/microphone type, noise condition, speaker-independent split identity and
the intended EKEEKRTA action. Include difficult negative samples: unrelated
speech, silence, background conversations, secrets and commands unavailable to
the speaker's role.

Keep speakers disjoint across training, validation and test sets. Evaluate word
error rate, exact entity accuracy for course codes/dates/times, intent accuracy,
false activation rate and confidence calibration for each language/accent/noise
group. Release only after institution-approved thresholds are met. Until then,
leave the model settings empty and the UI will accurately report voice as
unavailable.
