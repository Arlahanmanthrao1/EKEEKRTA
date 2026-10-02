import { useState } from "react";
import { createStudent, createFaculty, createHod } from "../../api/client";

const emptyForm = { name: "", email: "", institutional_id: "", department: "", program: "", batch: "", semester_number: "", section: "", password: "", confirmPassword: "" };

export default function AccountRegistrationForm({ accountType = "student", onCreated, departments = [], institutionType = "university" }) {
  const isFaculty = accountType === "faculty";
  const isHod = accountType === "hod";
  const isTraining = institutionType === "training_institution";
  const label = isHod ? "HOD" : isFaculty ? (isTraining ? "Trainer" : "Faculty") : "Student";
  const groupLabel = isTraining ? "Domain" : "Department";
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
        department: form.department || null, program: !isTraining ? form.program || null : null,
        batch: !isTraining ? form.batch || null : null,
        semester_number: !isTraining && form.semester_number ? Number(form.semester_number) : null,
        section: !isTraining ? form.section || null : null, institutional_id: form.institutional_id || null, password: form.password });
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
      <div className="section-title-row"><div><p className="section-eyebrow">Administrator access</p><h2 className="section-title">{isHod ? "Create HOD" : isFaculty ? `Create ${label.toLowerCase()}` : "Register student"}</h2></div></div>
      <p className="footnote">Create a {label.toLowerCase()} login using their approved institution email. {isHod ? "HODs can view only faculty and students in their assigned department; they cannot administer accounts." : isFaculty ? `${isTraining ? "Trainers" : "Faculty"} can access only their courses and enrolled students.` : `Students cannot register themselves. Use the student’s official ${isTraining ? "learner" : "roll or registration"} ID as the stable institution identifier.`} Share credentials privately; no email is sent automatically.</p>
      {!departments.length && <p className="footnote">Create a {groupLabel.toLowerCase()} first using the {groupLabel}s page.</p>}
      <form onSubmit={submit} className="form-grid">
        <label className="field-label">Full name<input className="field" name="name" value={form.name} onChange={update} required minLength={2} maxLength={120} autoComplete="off" /></label>
        <label className="field-label">Institution email<input className="field" name="email" type="email" value={form.email} onChange={update} required autoComplete="off" /></label>
        <label className="field-label">{groupLabel}<select className="field" name="department" value={form.department} onChange={update} required><option value="">Select {groupLabel.toLowerCase()}</option>{departments.map((department) => <option key={department.id} value={department.name}>{department.name}</option>)}</select></label>
        <label className="field-label">{isFaculty || isHod ? `Official ${isTraining ? "trainer" : "employee"} ID` : isTraining ? "Official learner ID" : "Registration / roll number"}<input className="field" name="institutional_id" placeholder={`Official ${isFaculty && isTraining ? "trainer" : isTraining ? "learner" : isFaculty || isHod ? "institution employee" : "institution student"} ID`} value={form.institutional_id} onChange={update} required minLength={2} maxLength={120} /></label>
        {!isTraining && !isFaculty && !isHod && <>
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
