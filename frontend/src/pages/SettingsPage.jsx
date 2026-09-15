import { useState } from "react";
import { apiFetch } from "../api/client";
import DashboardShell from "../components/dashboard/DashboardShell";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import "../styles/dashboard.css";

const roleLabels = { admin: "Administrator", faculty: "Faculty", hod: "HOD", student: "Student" };
const personalOptions = [
  { value: "institution", label: "Institution default", detail: "Use the appearance chosen by your administrator." },
  { value: "light", label: "Light", detail: "A bright workspace for daytime use." },
  { value: "dark", label: "Dark", detail: "A low-glare workspace for dim environments." },
  { value: "system", label: "Device setting", detail: "Follow this device’s light or dark appearance." },
];
const institutionOptions = personalOptions.filter(option => option.value !== "institution");

function ThemeChoices({ name, options, value, onChange }) {
  return <div className="theme-choice-grid">{options.map(option => <label className={`theme-choice ${value === option.value ? "selected" : ""}`} key={option.value}>
    <input type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
    <span className={`theme-preview theme-preview-${option.value}`} aria-hidden="true"><i /><i /><i /></span>
    <strong>{option.label}</strong><small>{option.detail}</small>
  </label>)}</div>;
}

export default function SettingsPage() {
  const { user, logout, refreshUser } = useAuth();
  const { preference, setPreference, institutionDefault, setInstitutionDefault } = useTheme();
  const [institutionChoice, setInstitutionChoice] = useState(institutionDefault);
  const [grading, setGrading] = useState({ grading_scale_max: user.institution?.grading_scale_max ?? 10,
    passing_grade_point: user.institution?.passing_grade_point ?? 4 });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const saveInstitutionTheme = async () => {
    setBusy(true); setMessage(""); setError("");
    try {
      const institution = await apiFetch("/institutions/current/theme", {
        method: "PATCH", body: JSON.stringify({ default_theme: institutionChoice }),
      });
      setInstitutionDefault(institution.default_theme);
      await refreshUser(true);
      setMessage("Institution default theme saved for all users.");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const saveGrading = async event => {
    event.preventDefault(); setBusy(true); setMessage(""); setError("");
    try {
      await apiFetch("/institutions/current/grading", { method: "PATCH", body: JSON.stringify({
        grading_scale_max: Number(grading.grading_scale_max), passing_grade_point: Number(grading.passing_grade_point),
      }) });
      await refreshUser(true); setMessage("Institution grading rules saved.");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  return <DashboardShell user={user} title="Settings" roleLabel={roleLabels[user.role]} onLogout={logout}>
    <div className="settings-layout">
      {error && <p className="error-banner" role="alert">{error}</p>}
      {message && <p className="success-banner" role="status">{message}</p>}
      <section className="card panel-card settings-card">
        <p className="section-eyebrow">Your account</p><h2 className="section-title">Appearance</h2>
        <p className="settings-description">Choose how EKEEKRTA looks on this browser. This does not change anyone else’s dashboard.</p>
        <ThemeChoices name="personal-theme" options={personalOptions} value={preference} onChange={setPreference} />
      </section>
      {user.role === "admin" && <section className="card panel-card settings-card">
        <p className="section-eyebrow">Institution controls</p><h2 className="section-title">Default appearance</h2>
        <p className="settings-description">This is the starting theme for everyone in {user.institution?.name}. Personal overrides remain unchanged.</p>
        <ThemeChoices name="institution-theme" options={institutionOptions} value={institutionChoice} onChange={setInstitutionChoice} />
        <button className="btn btn-primary" type="button" disabled={busy || institutionChoice === institutionDefault} onClick={saveInstitutionTheme}>{busy ? "Saving…" : "Save institution default"}</button>
      </section>}
      {user.role === "admin" && <section className="card panel-card settings-card">
        <p className="section-eyebrow">Institution controls</p><h2 className="section-title">Grading rules</h2>
        <p className="settings-description">These official rules control every student CGPA projection. They do not alter ERP marks.</p>
        <form className="form-grid" onSubmit={saveGrading}><label className="field-label">CGPA scale maximum<input className="field" type="number" min="4" max="100" step="0.01" value={grading.grading_scale_max} onChange={event => setGrading(current => ({ ...current, grading_scale_max: event.target.value }))} required /></label><label className="field-label">Passing grade point<input className="field" type="number" min="0" max={grading.grading_scale_max} step="0.01" value={grading.passing_grade_point} onChange={event => setGrading(current => ({ ...current, passing_grade_point: event.target.value }))} required /></label><div className="wide"><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save grading rules"}</button></div></form>
      </section>}
    </div>
  </DashboardShell>;
}
