# University Data Exchange

The Data Exchange workspace solves a university-specific workflow: faculty record course data once in Ekeekrta, but other university systems may require differently named and ordered CSV columns.

## Faculty workflow

1. Open **Faculty portal → Data Exchange**.
2. Select one of the faculty member's assigned courses and choose a dataset:
   - course roster;
   - meeting attendance;
   - assignment marks; or
   - quiz scores.
3. Upload a blank CSV template downloaded from the destination university platform. Ekeekrta reads only the first non-empty header row.
4. Map every destination column to an Ekeekrta field, or explicitly leave it blank.
5. Apply an optional value transformation, review the preview and blank-cell count, then download the converted CSV.
6. Save the mapping as a private profile for later exports. Saved profiles can be updated or deleted.

Ekeekrta does not sign in to or submit data to the destination platform. A faculty member reviews the generated CSV before uploading it there.

## Access and safety rules

- The feature is available only to faculty in institutions registered as `university`.
- Training institutions do not see the navigation item, route, or API data.
- A faculty member can load only courses assigned to that faculty account.
- Saved mapping profiles are isolated by institution and faculty owner.
- Student data is never invented: exports contain only records stored in Ekeekrta.
- Source exports are limited to 5,000 enrolled learners and 20,000 records per request.
- CSV templates are limited to 1 MB and 200 unique columns.

## Current format support

The first version accepts CSV templates and generates UTF-8 CSV files. Direct submission to third-party university platforms and Excel workbook templates are intentionally out of scope for this version.
