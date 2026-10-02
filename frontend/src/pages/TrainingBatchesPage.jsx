import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuth } from "../context/AuthContext";
import DashboardShell, { EmptyState, StatCard } from "../components/dashboard/DashboardShell";
import GoogleDriveFolderPicker from "../components/GoogleDriveFolderPicker";
import "../styles/dashboard.css";
import "../styles/training.css";

const emptyBatch = { course_id: "", trainer_id: "", name: "", code: "", start_date: "",
  end_date: "", status: "planned", capacity: 30, recording_drive_folder_id: "",
  certificate_enabled: true, certificate_min_progress: 80, certificate_min_attendance: 75 };

export default function TrainingBatchesPage() {
  const { user, logout } = useAuth();
  const manager = user.role === "admin" || user.role === "faculty";
  const [batches, setBatches] = useState([]);
  const [courses, setCourses] = useState([]);
  const [trainers, setTrainers] = useState([]);
  const [domains, setDomains] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [form, setForm] = useState(emptyBatch);
  const [program, setProgram] = useState({ name: "", code: "", department: user.department || "" });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const calls = [apiFetch("/training/batches")];
        if (manager) calls.push(apiFetch("/courses/"), apiFetch("/training/analytics"), apiFetch("/institutions/departments"));
        if (user.role === "admin") calls.push(apiFetch("/users/"));
        const result = await Promise.all(calls);
        if (!active) return;
        setBatches(result[0]);
        if (manager) { setCourses(result[1]); setAnalytics(result[2]); setDomains(result[3]); }
        if (user.role === "admin") setTrainers(result[4].filter(account => account.role === "faculty"));
        setError("");
      } catch (err) { if (active) setError(err.message); }
      finally { if (active) setLoading(false); }
    }
    load();
    return () => { active = false; };
  }, [manager, reload, user.id, user.role]);

  async function createBatch(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const payload = { ...form, course_id: Number(form.course_id), capacity: Number(form.capacity),
        certificate_min_progress: Number(form.certificate_min_progress),
        certificate_min_attendance: Number(form.certificate_min_attendance) };
      if (user.role === "faculty") delete payload.trainer_id;
      else payload.trainer_id = Number(payload.trainer_id);
      if (!payload.recording_drive_folder_id) delete payload.recording_drive_folder_id;
      await apiFetch("/training/batches", { method: "POST", body: JSON.stringify(payload) });
      setForm(emptyBatch); setNotice("Batch created. You can now add learners, modules and classes.");
      setReload(value => value + 1);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function createProgram(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch("/courses/", { method: "POST", body: JSON.stringify({ ...program,
        course_type: "academic", enrollment_mode: "elective" }) });
      setProgram({ name: "", code: "", department: user.department || "" });
      setNotice("Training program created. It is now available for a batch."); setReload(value => value + 1);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const base = `/${user.role}/training-batches`;
  return <DashboardShell user={user} title="Training batches" roleLabel={user.role === "faculty" ? "Trainer" : user.role === "student" ? "Learner" : "Administrator"} onLogout={logout} activePage="batches">
    {error && <p className="error-banner" role="alert">{error}</p>}
    {notice && <p className="success-banner" role="status">{notice}</p>}
    {manager && analytics && <div className="stats-grid training-stats">
      <StatCard icon="courses" label="Batches" value={analytics.batch_count} detail={`${analytics.statuses.active || 0} active`} />
      <StatCard icon="users" label="Unique learners" value={analytics.unique_learners} tone="mint" detail={`${analytics.capacity_utilization}% capacity used`} />
      <StatCard icon="chart" label="Average progress" value={`${analytics.average_progress}%`} tone="purple" detail={analytics.average_attendance === null ? "No meeting attendance yet" : `${analytics.average_attendance}% attendance`} />
      <StatCard icon="check" label="Certificate ready" value={analytics.eligible_certificates} tone="amber" detail={`${analytics.completion_percent}% marked complete`} />
    </div>}

    <div className={`training-batches-layout ${manager ? "with-builder" : ""}`}>
      <section className="card panel-card">
        <div className="section-title-row"><div><p className="section-eyebrow">Training delivery</p><h2>{manager ? "Batches" : "My batches"}</h2></div><span className="pill pill-muted">{batches.length}</span></div>
        {loading && <p role="status">Loading batches…</p>}
        {!loading && !batches.length && <EmptyState>{manager ? "Create the first batch after a training program and trainer are ready." : "You have not been enrolled in a batch yet."}</EmptyState>}
        <div className="training-batch-grid">{batches.map(batch => <article className="training-batch-card" key={batch.id}>
          <div className="split-row"><span className={`pill batch-status-${batch.status}`}>{batch.status}</span><strong>{batch.learner_count}/{batch.capacity}</strong></div>
          <h3>{batch.name}</h3><p>{batch.course_code} · {batch.course_name}</p>
          <dl><div><dt>Trainer</dt><dd>{batch.trainer_name}</dd></div><div><dt>Duration</dt><dd>{new Date(`${batch.start_date}T00:00:00`).toLocaleDateString()} – {new Date(`${batch.end_date}T00:00:00`).toLocaleDateString()}</dd></div></dl>
          <Link className="btn btn-primary" to={`${base}/${batch.id}`}>Open batch workspace</Link>
        </article>)}</div>
      </section>

      {manager && <section className="card panel-card batch-builder">
        <p className="section-eyebrow">New delivery</p><h2>Create batch</h2>
        <details className="program-builder" open={!courses.length}><summary>Create a training program</summary><form className="form-grid one-column" onSubmit={createProgram}><label className="field-label">Program name<input className="field" required value={program.name} onChange={event => setProgram({ ...program, name: event.target.value })} placeholder="Full Stack Web Development" /></label><label className="field-label">Program code<input className="field" required value={program.code} onChange={event => setProgram({ ...program, code: event.target.value.toUpperCase() })} placeholder="FSWD" /></label><label className="field-label">Domain<select className="field" required value={program.department} onChange={event => setProgram({ ...program, department: event.target.value })}><option value="">Select domain</option>{domains.map(domain => <option key={domain.id} value={domain.name}>{domain.name}</option>)}</select></label><button className="btn btn-soft" disabled={busy}>Create program</button></form></details>
        {!courses.length && <p className="error-banner">Create a training program first. A program can be delivered through multiple batches.</p>}
        <form className="form-grid one-column" onSubmit={createBatch}>
          <label className="field-label">Training program<select className="field" required value={form.course_id} onChange={event => setForm({ ...form, course_id: event.target.value })}><option value="">Select program</option>{courses.map(course => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}</select></label>
          {user.role === "admin" && <label className="field-label">Assigned trainer<select className="field" required value={form.trainer_id} onChange={event => setForm({ ...form, trainer_id: event.target.value })}><option value="">Select trainer</option>{trainers.map(trainer => <option key={trainer.id} value={trainer.id}>{trainer.name} · {trainer.department || "No domain"}</option>)}</select></label>}
          <label className="field-label">Batch name<input className="field" required minLength={2} maxLength={160} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} placeholder="Full Stack · October morning" /></label>
          <label className="field-label">Batch code<input className="field" required minLength={2} maxLength={80} value={form.code} onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} placeholder="FS-OCT-26-A" /></label>
          <div className="two-field-row"><label className="field-label">Start date<input className="field" type="date" required value={form.start_date} onChange={event => setForm({ ...form, start_date: event.target.value })} /></label><label className="field-label">End date<input className="field" type="date" required value={form.end_date} min={form.start_date} onChange={event => setForm({ ...form, end_date: event.target.value })} /></label></div>
          <div className="two-field-row"><label className="field-label">Status<select className="field" value={form.status} onChange={event => setForm({ ...form, status: event.target.value })}><option value="planned">Planned</option><option value="active">Active</option></select></label><label className="field-label">Capacity<input className="field" type="number" min="1" max="10000" required value={form.capacity} onChange={event => setForm({ ...form, capacity: event.target.value })} /></label></div>
          {user.role === "faculty" && <GoogleDriveFolderPicker value={form.recording_drive_folder_id} onChange={value => setForm({ ...form, recording_drive_folder_id: value })} />}
          <details><summary>Certificate rules</summary><div className="two-field-row"><label className="field-label">Minimum progress %<input className="field" type="number" min="0" max="100" value={form.certificate_min_progress} onChange={event => setForm({ ...form, certificate_min_progress: event.target.value })} /></label><label className="field-label">Minimum attendance %<input className="field" type="number" min="0" max="100" value={form.certificate_min_attendance} onChange={event => setForm({ ...form, certificate_min_attendance: event.target.value })} /></label></div></details>
          <button className="btn btn-primary" disabled={busy || !courses.length}>{busy ? "Creating…" : "Create batch"}</button>
        </form>
      </section>}
    </div>
  </DashboardShell>;
}
