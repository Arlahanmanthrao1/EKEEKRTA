import { useState } from "react";
import { apiFetch } from "../api/client";
import { BrandLogo, usePageTitle } from "../branding/Brand";
import { useAuth } from "../context/AuthContext";
import "../styles/dashboard.css";

export default function ChangePasswordPage() {
  const { refreshUser, logout } = useAuth();
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  usePageTitle("Change temporary password");

  const update = (event) => setForm({ ...form, [event.target.name]: event.target.value });
  const submit = async (event) => {
    event.preventDefault(); setError("");
    if (form.new_password !== form.confirm) return setError("New passwords do not match.");
    setBusy(true);
    try {
      await apiFetch("/auth/change-password", { method: "POST", body: JSON.stringify({
        current_password: form.current_password,
        new_password: form.new_password,
      }) });
      await refreshUser(true);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return <main className="login-page brand-login"><section className="login-art"><BrandLogo inverse /><div><h1>Secure your<br /><em>EKEEKRTA account.</em></h1><p className="login-art-description">Your Official ID is only a temporary first-login password.</p></div></section><section className="login-panel"><div className="login-card"><BrandLogo /><h2>Change temporary password</h2><p>Create a private password before continuing to your dashboard.</p><form className="login-form" onSubmit={submit}><label className="field-label">Temporary password (your Official ID)<input className="field" name="current_password" type="password" value={form.current_password} onChange={update} required autoComplete="current-password" /></label><label className="field-label">New password<input className="field" name="new_password" type="password" value={form.new_password} onChange={update} required minLength={8} maxLength={72} autoComplete="new-password" /></label><label className="field-label">Confirm new password<input className="field" name="confirm" type="password" value={form.confirm} onChange={update} required minLength={8} maxLength={72} autoComplete="new-password" /></label>{error && <p className="error-banner" role="alert">{error}</p>}<button className="btn btn-primary" disabled={busy}>{busy ? "Changing password…" : "Set new password"}</button><button className="btn btn-soft" type="button" onClick={logout} disabled={busy}>Sign out</button></form></div></section></main>;
}
