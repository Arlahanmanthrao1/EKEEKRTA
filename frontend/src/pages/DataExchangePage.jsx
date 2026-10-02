import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import DashboardShell, { EmptyState } from "../components/dashboard/DashboardShell";
import "../styles/dashboard.css";
import "../styles/data-exchange.css";

const datasets = [
  ["roster", "Course roster"], ["attendance", "Meeting attendance"],
  ["assignment_marks", "Assignment marks"], ["quiz_scores", "Quiz scores"],
];
const transforms = [
  ["none", "Keep original"], ["uppercase", "UPPERCASE"], ["lowercase", "lowercase"],
  ["date_dmy", "Date: DD/MM/YYYY"], ["present_pa", "Boolean: P/A"], ["present_10", "Boolean: 1/0"],
];

function parseCsvHeaders(text) {
  const firstLine = text.replace(/^\uFEFF/, "").split(/\r?\n/).find(line => line.trim());
  if (!firstLine) throw new Error("The CSV template is empty.");
  const values = []; let value = "", quoted = false;
  for (let index = 0; index < firstLine.length; index += 1) {
    const character = firstLine[index];
    if (character === '"' && quoted && firstLine[index + 1] === '"') { value += '"'; index += 1; }
    else if (character === '"') quoted = !quoted;
    else if (character === "," && !quoted) { values.push(value.trim()); value = ""; }
    else value += character;
  }
  values.push(value.trim());
  if (values.some(header => !header)) throw new Error("Every template column must have a heading.");
  if (new Set(values.map(header => header.toLowerCase())).size !== values.length) throw new Error("Template headings must be unique.");
  if (values.length > 200) throw new Error("Templates can contain at most 200 columns.");
  return values;
}

function transformValue(value, transform) {
  if (value === null || value === undefined) return "";
  if (transform === "uppercase") return String(value).toUpperCase();
  if (transform === "lowercase") return String(value).toLowerCase();
  if (transform === "present_pa") return value === true || value === 1 || String(value).toLowerCase() === "true" ? "P" : "A";
  if (transform === "present_10") return value === true || value === 1 || String(value).toLowerCase() === "true" ? "1" : "0";
  if (transform === "date_dmy") {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? `${String(date.getDate()).padStart(2, "0")}/${String(date.getMonth() + 1).padStart(2, "0")}/${date.getFullYear()}` : "";
  }
  return String(value);
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export default function DataExchangePage() {
  const { user, logout } = useAuth();
  const fileRef = useRef(null);
  const [courses, setCourses] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [courseId, setCourseId] = useState("");
  const [dataType, setDataType] = useState("roster");
  const [source, setSource] = useState(null);
  const [headers, setHeaders] = useState([]);
  const [mapping, setMapping] = useState({});
  const [templateName, setTemplateName] = useState("");
  const [profileName, setProfileName] = useState("");
  const [targetPlatform, setTargetPlatform] = useState("");
  const [selectedProfile, setSelectedProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadProfiles = () => apiFetch("/data-exchange/profiles").then(setProfiles);
  useEffect(() => {
    Promise.all([apiFetch("/courses/"), apiFetch("/data-exchange/profiles")])
      .then(([courseRows, profileRows]) => { setCourses(courseRows); setProfiles(profileRows); })
      .catch(err => setError(err.message));
  }, [user.id]);

  useEffect(() => { setSource(null); }, [courseId, dataType]);

  async function loadSource() {
    if (!courseId) return;
    setBusy(true); setError(""); setNotice("");
    try { setSource(await apiFetch(`/data-exchange/source/${dataType}?course_id=${Number(courseId)}`)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function uploadTemplate(event) {
    const file = event.target.files?.[0]; if (!file) return;
    setError(""); setNotice("");
    try {
      if (!file.name.toLowerCase().endsWith(".csv")) throw new Error("Upload a CSV template. Excel workbook support will be added separately.");
      if (file.size > 1_000_000) throw new Error("CSV templates must be 1 MB or smaller.");
      const nextHeaders = parseCsvHeaders(await file.text());
      setHeaders(nextHeaders); setTemplateName(file.name); setSelectedProfile("");
      setMapping(Object.fromEntries(nextHeaders.map(header => [header, { source: "", transform: "none" }])));
      setNotice(`${nextHeaders.length} template columns detected. Map each column below.`);
    } catch (err) { setError(err.message); }
    event.target.value = "";
  }

  function chooseProfile(id) {
    setSelectedProfile(id);
    const profile = profiles.find(row => row.id === Number(id));
    if (!profile) return;
    setDataType(profile.data_type); setHeaders(profile.template_headers); setMapping(profile.mapping);
    setProfileName(profile.name); setTargetPlatform(profile.target_platform); setTemplateName(`${profile.name} · saved profile`);
    setSource(null); setNotice("Saved mapping loaded. Choose a course and load its data.");
  }

  const outputRows = useMemo(() => (source?.records || []).map(record => Object.fromEntries(headers.map(header => {
    const rule = mapping[header];
    return [header, rule?.source === "__blank__" ? "" : transformValue(record[rule?.source], rule?.transform)];
  }))), [headers, mapping, source]);
  const unmapped = headers.filter(header => !mapping[header]?.source);
  const blankCount = outputRows.reduce((count, row) => count + headers.filter(header => !row[header]).length, 0);

  async function saveProfile(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const profileId = Number(selectedProfile);
      const saved = await apiFetch(profileId ? `/data-exchange/profiles/${profileId}` : "/data-exchange/profiles", { method: profileId ? "PUT" : "POST", body: JSON.stringify({
        name: profileName, target_platform: targetPlatform, data_type: dataType,
        template_headers: headers, mapping,
      }) });
      await loadProfiles(); setSelectedProfile(String(saved.id));
      setNotice(profileId ? "Mapping profile updated." : "Reusable mapping profile saved for your faculty account.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function downloadCsv() {
    if (!source?.records?.length || unmapped.length) return;
    const content = [headers.map(csvCell).join(","), ...outputRows.map(row => headers.map(header => csvCell(row[header])).join(","))].join("\r\n");
    const blob = new Blob(["\uFEFF", content], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `${source.course.code}-${dataType}-${targetPlatform || "export"}.csv`.replace(/[^a-z0-9_.-]+/gi, "-");
    anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 0);
    if (selectedProfile) apiFetch(`/data-exchange/profiles/${selectedProfile}/used`, { method: "POST" }).then(loadProfiles).catch(() => {});
    setNotice(`${outputRows.length} validated records exported using the uploaded template structure.`);
  }

  return <DashboardShell user={user} title="Data Exchange" roleLabel="Faculty" onLogout={logout} activePage="data-exchange">
    <section className="data-exchange-hero card"><div><p className="section-eyebrow">Enter once · export correctly</p><h1>University Data Exchange</h1><p>Convert Ekeekrta course records into the exact CSV structure required by another university platform. Nothing is submitted automatically.</p></div><div className="exchange-flow"><span>1 · Source</span><span>2 · Template</span><span>3 · Map</span><span>4 · Validate</span><span>5 · Export</span></div></section>
    {error && <p className="error-banner" role="alert">{error}</p>}{notice && <p className="success-banner" role="status">{notice}</p>}

    <div className="data-exchange-layout"><main className="content-stack">
      <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Step 1</p><h2>Choose Ekeekrta data</h2></div><span className="pill pill-muted">University only</span></div><div className="exchange-source-fields"><label className="field-label">Course<select className="field" value={courseId} onChange={event => setCourseId(event.target.value)}><option value="">Select your course</option>{courses.map(course => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></label><label className="field-label">Dataset<select className="field" value={dataType} onChange={event => setDataType(event.target.value)}>{datasets.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><button className="btn btn-primary" disabled={!courseId || busy} onClick={loadSource}>{busy ? "Loading…" : "Load records"}</button></div>{source && <p className="exchange-result"><strong>{source.record_count}</strong> real records loaded from {source.course.code}. No missing records are fabricated.</p>}</section>

      <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Steps 2 and 3</p><h2>Upload and map a template</h2></div><button className="btn btn-soft" onClick={() => fileRef.current?.click()}>Upload CSV template</button></div><input hidden ref={fileRef} type="file" accept=".csv,text/csv" onChange={uploadTemplate} /><p className="footnote">Upload a blank CSV downloaded from the destination platform. Ekeekrta reads only its header row.</p>{templateName && <p className="template-name">Template: <strong>{templateName}</strong> · {headers.length} columns</p>}
        {!headers.length ? <EmptyState>Upload a CSV template or choose one of your saved mappings.</EmptyState> : <div className="mapping-table-wrap"><table className="ledger mapping-table"><thead><tr><th>Destination column</th><th>Ekeekrta field</th><th>Transformation</th></tr></thead><tbody>{headers.map(header => <tr key={header}><td><strong>{header}</strong></td><td><select className="field" value={mapping[header]?.source || ""} onChange={event => setMapping(current => ({ ...current, [header]: { source: event.target.value, transform: current[header]?.transform || "none" } }))}><option value="">Select field</option><option value="__blank__">Leave this column blank</option>{source?.fields.map(field => <option key={field.name} value={field.name}>{field.label} · {field.name}</option>)}</select></td><td><select className="field" value={mapping[header]?.transform || "none"} disabled={!mapping[header]?.source || mapping[header]?.source === "__blank__"} onChange={event => setMapping(current => ({ ...current, [header]: { ...current[header], transform: event.target.value } }))}>{transforms.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></td></tr>)}</tbody></table></div>}
      </section>

      <section className="card panel-card"><div className="section-title-row"><div><p className="section-eyebrow">Steps 4 and 5</p><h2>Validate, preview and export</h2></div></div>{!source || !headers.length ? <EmptyState>Load a dataset and map a template to generate a preview.</EmptyState> : <><div className="validation-strip"><span className={unmapped.length ? "validation-error" : "validation-ok"}>{unmapped.length ? `${unmapped.length} unmapped columns` : "All columns mapped"}</span><span>{outputRows.length} output rows</span><span>{blankCount} blank cells</span></div><div className="mapping-table-wrap"><table className="ledger preview-table"><thead><tr>{headers.map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{outputRows.slice(0, 8).map((row, index) => <tr key={index}>{headers.map(header => <td key={header}>{row[header] || <span className="blank-value">blank</span>}</td>)}</tr>)}</tbody></table></div><p className="footnote">Preview shows the first {Math.min(8, outputRows.length)} rows. Review blank cells before export.</p><button className="btn btn-primary" disabled={busy || Boolean(unmapped.length) || !outputRows.length} onClick={downloadCsv}>Download converted CSV</button></>}
      </section>
    </main>

    <aside className="content-stack exchange-sidebar"><section className="card panel-card"><p className="section-eyebrow">Reusable mappings</p><h2>Saved profiles</h2><label className="field-label">Load profile<select className="field" value={selectedProfile} onChange={event => chooseProfile(event.target.value)}><option value="">Choose saved mapping</option>{profiles.map(profile => <option value={profile.id} key={profile.id}>{profile.name} · {profile.target_platform}</option>)}</select></label>{!profiles.length && <p className="footnote">No profiles saved yet.</p>}<div className="saved-profile-list">{profiles.slice(0, 6).map(profile => <article key={profile.id}><div><strong>{profile.name}</strong><span>{profile.target_platform} · {profile.export_count} exports</span></div><button className="text-danger-button" onClick={async () => { setError(""); try { await apiFetch(`/data-exchange/profiles/${profile.id}`, { method: "DELETE" }); if (Number(selectedProfile) === profile.id) { setSelectedProfile(""); setProfileName(""); setTargetPlatform(""); } await loadProfiles(); setNotice("Mapping profile deleted."); } catch (err) { setError(err.message); } }}>Delete</button></article>)}</div></section>
      <section className="card panel-card"><div className="section-title-row"><h2>{selectedProfile ? "Update mapping" : "Save current mapping"}</h2>{selectedProfile && <button type="button" className="text-button" onClick={() => { setSelectedProfile(""); setProfileName(""); setTargetPlatform(""); }}>Save as new</button>}</div><form className="form-grid one-column" onSubmit={saveProfile}><label className="field-label">Profile name<input className="field" required minLength={2} value={profileName} onChange={event => setProfileName(event.target.value)} placeholder="Internal marks template" /></label><label className="field-label">Destination platform<input className="field" required minLength={2} value={targetPlatform} onChange={event => setTargetPlatform(event.target.value)} placeholder="University exam portal" /></label><button className="btn btn-soft" disabled={busy || !headers.length || Boolean(unmapped.length)}>{selectedProfile ? "Update mapping" : "Save mapping"}</button></form></section>
      <section className="card panel-card exchange-safety"><h3>Safe by design</h3><ul><li>Faculty can export only their assigned courses.</li><li>The destination file is downloaded for review.</li><li>No external platform receives data automatically.</li><li>Saved mappings are private to your faculty account.</li></ul></section>
    </aside></div>
  </DashboardShell>;
}
