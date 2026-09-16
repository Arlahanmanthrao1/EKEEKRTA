# EKEEKRTA Stage 4 local-model contract

Stage 4 never downloads a model and never calls an external inference API. The
institution supplies reviewed executables and immutable model IDs in the backend
environment. The worker passes local private paths without invoking a shell.

## Speech executable

Invocation:

```text
<speech-executable> --input-audio <mono-16khz-wav> --output-json <temporary-json>
```

Required output:

```json
{
  "schema_version": 1,
  "language": "en",
  "segments": [
    {
      "start_ms": 0,
      "end_ms": 6400,
      "speaker": "Faculty",
      "confidence": 0.91,
      "text": "Verified recognized speech goes here."
    }
  ]
}
```

Segments must be time ordered, bounded, nonempty and individually scored from
zero to one. The combined private transcript must contain 180–100,000
characters. Invalid JSON, unexpected schema versions, missing output, oversized
output, non-monotonic timestamps and invalid confidence values fail closed.

## Optional slide OCR executable

Invocation:

```text
<ocr-executable> --input-frames <sampled-jpeg-directory> --output-json <temporary-json>
```

Required output:

```json
{
  "schema_version": 1,
  "slides": [
    {"timestamp_ms": 30000, "confidence": 0.88, "text": "Recognized slide text"}
  ]
}
```

At most 500 slide observations are accepted. OCR evidence is appended to the
private transcript draft and therefore receives the same faculty review; it is
not independently published.

## Dataset needed to build EKEEKRTA-owned models

The code contract is complete, but training cannot begin without institutionally
approved data. Collect consented lecture recordings and human transcripts that
represent the actual languages, accents, course terminology, microphones,
background noise and screen-sharing conditions. Keep speaker/course cohorts
separate across training, validation and test splits to prevent leakage.

For speech, preserve timestamped utterances, speaker labels and a reviewed text
normalization policy. For OCR, preserve the source frame, exact transcription,
language/script, slide-versus-camera label and duplicate-slide grouping. Remove
or restrict personal and sensitive data before it enters a training set.

Evaluate speech word/character error rates, course-term recall, speaker error and
confidence calibration. Evaluate OCR character/word error by slide type. Set
acceptance thresholds from a real pilot; EKEEKRTA must not invent a universal
accuracy claim. A model that does not pass the institution's held-out test set
must not be configured in production.

## Human control

Model output always becomes a private draft. Faculty can correct the transcript,
select or exclude each proposed statement, approve topic labels and publish or
unpublish notes. Students never receive raw recordings, raw transcripts,
candidate statements, model confidence or unreviewed slide text.
