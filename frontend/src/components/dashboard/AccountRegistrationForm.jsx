import { useState } from "react";
import { createStudent, createFaculty, createHod } from "../../api/client";

const emptyForm = { name: "", email: "", institutional_id: "", department: "", program: "", batch: "", semester_number: "", section: "", password: "", confirmPassword: "" };

export default function AccountRegistrationForm({ accountType = "student", onCreated, departments = [] }) {
  const isFaculty = accountType === "faculty";
  const isHod = accountType === "hod";
  const label = isHod ? "HOD" : isFaculty ? "Faculty" : "Student";
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const update = (event) => setForm((current) => ({ ...current, [event.target.name]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const account = await (isHod ? createHod : isFaculty ? createFaculty : createStudent)({ name: form.name, email: form.email,
        department: form.department || null, program: form.program || null, batch: form.batch || null,
        semester_number: form.semester_number ? Number(form.semester_number) : null,
        section: form.section || null, institutional_id: form.institutional_id || null, password: form.password });
      onCreated(account);
      setForm(emptyForm);
      setSuccess(`${label} account created for ${account.name}. Share their login details privately.`);
    } catch (err) {
      setError(err.message || `Could not create ${label.toLowerCase()} account.`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="section card panel-card" id={`register-${accountType}`}>
      <div className="section-title-row"><div><p className="section-eyebrow">Administrator access</p><h2 className="section-title">{isHod ? "Create HOD" : isFaculty ? "Create faculty" : "Register student"}</h2></div></div>
      <p className="footnote">Create a {label.toLowerCase()} login using their approved institution email. {isHod ? "HODs can view only faculty and students in their assigned department; they cannot administer accounts." : isFaculty ? "Faculty can access only their courses and enrolled students." : "Students cannot register themselves. If ERP import is also enabled, use the same official roll number so a later import updates this profile instead of creating another one."} Share credentials privately; no email is sent automatically.</p>
      {!departments.length && <p className="footnote">Create a department first using the Departments page.</p>}
      <form onSubmit={submit} className="form-grid">
        <label className="field-label">Full name<input className="field" name="name" value={form.name} onChange={update} required minLength={2} maxLength={120} autoComplete="off" /></label>
        <label className="field-label">Institution email<input className="field" name="email" type="email" value={form.email} onChange={update} required autoComplete="off" /></label>
        <label className="field-label">Department<select className="field" name="department" value={form.department} onChange={update} required><option value="">Select department</option>{departments.map((department) => <option key={department.id} value={department.name}>{department.name}</option>)}</select></label>
        <label className="field-label">{isFaculty || isHod ? "Official employee ID" : "Registration / roll number"}<input className="field" name="institutional_id" placeholder={isFaculty || isHod ? "Official ERP employee ID" : "Official ERP student ID"} value={form.institutional_id} onChange={update} required minLength={2} maxLength={120} /></label>
        {!isFaculty && !isHod && <>
          <label className="field-label">Program<input className="field" name="program" placeholder="B.Tech Computer Science" value={form.program} onChange={update} required maxLength={120} /></label>
          <label className="field-label">Batch<input className="field" name="batch" placeholder="2026–2030" value={form.batch} onChange={update} required maxLength={40} /></label>
          <label className="field-label">Current semester<select className="field" name="semester_number" value={form.semester_number} onChange={update} required><option value="">Select semester</option>{Array.from({ length: 8 }, (_, index) => <option key={index + 1} value={index + 1}>Semester {index + 1} · Year {Math.ceil((index + 1) / 2)}</option>)}</select></label>
          <label className="field-label">Section<input className="field" name="section" placeholder="A" value={form.section} onChange={update} required maxLength={40} /></label>
        </>}
        <label className="field-label">Password<input className="field" name="password" type="password" value={form.password} onChange={update} required minLength={8} maxLength={72} autoComplete="new-password" /></label>
        <label className="field-label">Confirm password<input className="field" name="confirmPassword" type="password" value={form.confirmPassword} onChange={update} required minLength={8} maxLength={72} autoComplete="new-password" /></label>
        {error && <p className="error-banner wide" role="alert">{error}</p>}
        {success && <p className="success-banner wide" role="status">{success}</p>}
        <div className="wide"><button type="submit" disabled={submitting || !departments.length} className="btn btn-primary">{submitting ? "Creating account…" : `Create ${label.toLowerCase()} account`}</button></div>
      </form>
    </section>
  );
}
