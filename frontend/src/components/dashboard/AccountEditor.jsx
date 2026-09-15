import { useState } from "react";
import { apiFetch } from "../../api/client";

export default function AccountEditor({ account, departments, onSaved, onCancel }) {
  const [name, setName] = useState(account.name);
  const [department, setDepartment] = useState(account.department || "");
  const [program, setProgram] = useState(account.program || "");
  const [batch, setBatch] = useState(account.batch || "");
  const [semesterNumber, setSemesterNumber] = useState(account.semester_number || "");
  const [section, setSection] = useState(account.section || "");
  const [institutionalId, setInstitutionalId] = useState(account.institutional_id || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const saved = await apiFetch(`/users/${account.id}`, { method: "PATCH", body: JSON.stringify({ name, department: department || null,
        ...(account.role !== "admin" ? { institutional_id: institutionalId } : {}),
        ...(account.role === "student" ? { program, batch, semester_number: Number(semesterNumber), section } : {}) }) });
      onSaved(saved);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return <section className="card panel-card"><h2>Edit {account.name}</h2>
    <p>{account.email} · {account.role}. Updating a department changes HOD visibility immediately; course ownership and enrollments are preserved.</p>
    <form className="form-grid" onSubmit={submit}>
      <label className="field-label">Name<input className="field" value={name} onChange={(event) => setName(event.target.value)} required minLength={2} maxLength={120} /></label>
      <label className="field-label">Department<select className="field" value={department} onChange={(event) => setDepartment(event.target.value)} required={account.role !== "admin"}><option value="">Select department</option>{departments.map((entry) => <option key={entry.id} value={entry.name}>{entry.name}</option>)}</select></label>
      {account.role !== "admin" && <label className="field-label">{account.role === "student" ? "Registration / roll number" : "Official employee ID"}<input className="field" value={institutionalId} onChange={(event) => setInstitutionalId(event.target.value)} required minLength={2} maxLength={120} /></label>}
      {account.role === "student" && <>
        <label className="field-label">Program<input className="field" value={program} onChange={(event) => setProgram(event.target.value)} required maxLength={120} /></label>
        <label className="field-label">Batch<input className="field" value={batch} onChange={(event) => setBatch(event.target.value)} required maxLength={40} /></label>
        <label className="field-label">Current semester<select className="field" value={semesterNumber} onChange={(event) => setSemesterNumber(event.target.value)} required><option value="">Select semester</option>{Array.from({ length: 8 }, (_, index) => <option key={index + 1} value={index + 1}>Semester {index + 1} · Year {Math.ceil((index + 1) / 2)}</option>)}</select></label>
        <label className="field-label">Section<input className="field" value={section} onChange={(event) => setSection(event.target.value)} required maxLength={40} /></label>
      </>}
      {error && <p className="error-banner wide" role="alert">{error}</p>}
      <div className="wide hero-actions"><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save account"}</button><button className="btn btn-soft" type="button" onClick={onCancel} disabled={busy}>Cancel</button></div>
    </form>
  </section>;
}
