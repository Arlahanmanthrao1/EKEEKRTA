import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { BrandLogo, usePageTitle } from "../branding/Brand";
import "../styles/dashboard.css";

export default function ResetPasswordPage() {
  usePageTitle("Choose a new password");
  const [search] = useSearchParams();
  const token = search.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault(); setError(""); setMessage("");
    if (password !== confirm) { setError("Passwords do not match."); return; }
    setBusy(true);
    try {
      const result = await apiFetch("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password: password }) });
      setMessage(result.message); setPassword(""); setConfirm("");
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  return <main className="auth-page"><section className="auth-card">
    <BrandLogo />
    <p className="section-eyebrow">Secure reset</p>
    <h1>Choose a new password</h1>
    <p>Use 12–72 UTF-8 bytes. The reset link expires after a short time and works only once.</p>
    {!token && <p className="error-banner" role="alert">This password reset link is incomplete.</p>}
    {!message && <form className="login-form" onSubmit={submit}>
      <label className="field-label">New password<input className="field" type="password" minLength="12" maxLength="72" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <label className="field-label">Confirm new password<input className="field" type="password" minLength="12" maxLength="72" autoComplete="new-password" required value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <button className="btn btn-primary" disabled={busy || !token}>{busy ? "Resetting…" : "Reset password"}</button>
    </form>}
    {message && <p className="success-banner" role="status">{message}</p>}
    <Link className="auth-back-link" to="/login">Continue to sign in</Link>
  </section></main>;
}
