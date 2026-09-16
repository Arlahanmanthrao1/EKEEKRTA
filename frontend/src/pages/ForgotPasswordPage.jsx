import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { BrandLogo, usePageTitle } from "../branding/Brand";
import "../styles/dashboard.css";

export default function ForgotPasswordPage() {
  usePageTitle("Forgot password");
  const [email, setEmail] = useState("");
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch("/auth/password-recovery/config")
      .then((config) => setEnabled(Boolean(config.enabled)))
      .catch((requestError) => { setEnabled(false); setError(requestError.message); });
  }, []);

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await apiFetch("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
      setMessage(result.message);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  return <main className="auth-page"><section className="auth-card">
    <BrandLogo />
    <p className="section-eyebrow">Account recovery</p>
    <h1>Reset your password</h1>
    <p>Enter the institution email registered by your administrator. We will send a single-use reset link if the account is eligible.</p>
    {enabled === false && !error && <p className="notice-banner">Password recovery email is not configured yet. Contact your institution administrator.</p>}
    <form className="login-form" onSubmit={submit}>
      <label className="field-label">Institution email<input className="field" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      {message && <p className="success-banner" role="status">{message}</p>}
      {error && <p className="error-banner" role="alert">{error}</p>}
      <button className="btn btn-primary" disabled={busy || enabled !== true}>{busy ? "Sending…" : "Send reset link"}</button>
    </form>
    <Link className="auth-back-link" to="/login">Back to sign in</Link>
  </section></main>;
}
