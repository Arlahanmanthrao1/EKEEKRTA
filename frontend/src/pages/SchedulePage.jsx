import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../api/client";
import DashboardShell, { EmptyState } from "../components/dashboard/DashboardShell";
import "../styles/dashboard.css";
import "../styles/schedule.css";

export function ScheduleForm({ courses, fixedCourse, onSubmit, busy }) {
  const [form, setForm] = useState({ course_id: fixedCourse?.id || "", title: "", starts_at: "" });
  const [error, setError] = useState("");
  const submitting = useRef(false);
  async function submit(event) {
    event.preventDefault();
    if (submitting.current || busy) return;
    submitting.current = true;
    setError("");
    try {
      const startsAt = new Date(form.starts_at);
      if (!Number.isFinite(startsAt.getTime()) || startsAt <= new Date()) throw new Error("Choose a future date and time.");
      await onSubmit({ ...form, course_id: Number(form.course_id), starts_at: startsAt.toISOString() });
      setForm({ course_id: fixedCourse?.id || "", title: "", starts_at: "" });
    } catch (error) { setError(error.message); }
    finally { submitting.current = false; }
  }
  return <section className="card panel-card">
    <h2>Schedule a class</h2>
    <p>Optional: plan ahead, or use <Link to="/faculty/courses">Start class now</Link> whenever you’re ready.</p>
    <form className="form-grid one-column" onSubmit={submit}>
      {fixedCourse ? <p className="fixed-course-label"><span>Scheduling for</span><strong>{fixedCourse.code} · {fixedCourse.name}</strong></p> : <label className="field-label">Course<select className="field" required value={form.course_id} onChange={e => setForm({ ...form, course_id: e.target.value })} disabled={busy}>
        <option value="">Select your course</option>{courses.map(course => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
      </select></label>}
      <label className="field-label">Class title<input className="field" required maxLength={200} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} disabled={busy} /></label>
      <label className="field-label">Date and time<input className="field" type="datetime-local" required value={form.starts_at} onChange={e => setForm({ ...form, starts_at: e.target.value })} disabled={busy} />
        <small>Time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Students see the time in their local time zone.</small>
      </label>
      <p className="footnote">Students can join only after you select Start class. Scheduling does not mark attendance.</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <button className="btn btn-primary" disabled={busy || !courses.length}>{busy ? "Saving…" : "Schedule class"}</button>
    </form>
  </section>;
}

export function ScheduledClassList({ plans, busy, onStart, onCancel }) {
  const [confirm, setConfirm] = useState(null);
  const actionablePlans = plans.filter(plan => plan.status === "scheduled" || plan.status === "live");
  return <section className="card panel-card"><div className="section-title-row"><h2>Upcoming and live classes</h2><Link to="/faculty/calendar">View calendar →</Link></div>
    {!actionablePlans.length && <EmptyState>No upcoming or live classes. You can still start a new class from My Courses.</EmptyState>}
    <ul className="schedule-list">{actionablePlans.map(plan => <li key={plan.id}>
      <div><span className="section-eyebrow">{plan.status === "live" ? "Live" : "Scheduled"}</span><h3>{plan.title}</h3><p>{plan.course_code} · {plan.course_name}</p><time dateTime={plan.starts_at}>{new Date(plan.starts_at).toLocaleString()}</time>
        {plan.status === "scheduled" && new Date(plan.starts_at) < new Date() && <p className="footnote">Scheduled time has passed. Start when ready or cancel this plan.</p>}
      </div>
      <div className="schedule-actions"><button className="btn btn-primary" disabled={busy} onClick={() => onStart(plan)}>{plan.status === "live" ? "Rejoin class" : "Start class"}</button>
        {plan.status === "scheduled" && <button className="btn btn-soft" disabled={busy} onClick={() => setConfirm(plan.id)}>Cancel schedule</button>}
      </div>
      {confirm === plan.id && <div className="schedule-confirm"><p>Cancel “{plan.title}”? It will be marked cancelled in calendars.</p><button className="btn btn-soft" disabled={busy} onClick={async () => { if (await onCancel(plan)) setConfirm(null); }}>Yes, cancel class</button><button className="btn btn-soft" disabled={busy} onClick={() => setConfirm(null)}>Keep class</button></div>}
    </li>)}</ul>
  </section>;
}

export default function SchedulePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [courses, setCourses] = useState([]);
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const pending = useRef(false);
  useEffect(() => {
    let active = true, timer;
    async function load() {
      try {
        const [courses, plans] = await Promise.all([apiFetch("/courses/"), apiFetch("/schedule")]);
        if (active) { setCourses(courses); setPlans(plans); setError(""); }
      } catch (error) { if (active) setError(error.message); }
      finally { if (active) { setLoading(false); timer = setTimeout(load, 30000); } }
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [reload, user.id]);
  async function create(payload) {
    setBusy(true); setNotice("");
    try { await apiFetch("/schedule", { method: "POST", body: JSON.stringify(payload) }); setNotice("Class scheduled. It is now visible in course calendars."); setReload(n => n + 1); }
    finally { setBusy(false); }
  }
  async function act(plan, action) {
    if (pending.current) return false;
    pending.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const session = await apiFetch(`/schedule/${plan.id}/${action}`, { method: "POST" });
      if (action === "start") navigate("/classroom", { state: { sessionId: session.id, roomId: session.jitsi_room_id, courseId: plan.course_id, courseName: plan.course_name, studentId: user.id, studentName: user.name, isFaculty: true } });
      else { setNotice("Class schedule cancelled."); setReload(n => n + 1); }
      return true;
    } catch (error) { setError(error.message); return false; }
    finally { pending.current = false; setBusy(false); }
  }
  return <DashboardShell user={user} title="Schedule class" roleLabel={user.institution?.institution_type === "training_institution" ? "Trainer" : "Faculty"} onLogout={logout}>
    {error && <p className="error-banner" role="alert">{error} <button className="btn btn-soft" onClick={() => setReload(n => n + 1)}>Retry</button></p>}
    {notice && <p className="schedule-notice" role="status">{notice}</p>}
    {loading ? <p role="status">Loading your classes…</p> : <div className="schedule-layout"><ScheduleForm courses={courses} onSubmit={create} busy={busy} /><ScheduledClassList plans={plans} busy={busy} onStart={plan => act(plan, "start")} onCancel={plan => act(plan, "cancel")} /></div>}
  </DashboardShell>;
}
