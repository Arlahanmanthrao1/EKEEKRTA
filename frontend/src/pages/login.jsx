import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BrandLogo, brand, usePageTitle } from "../branding/Brand";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../api/client";
import { institutionHost } from "../api/institutionHost";
import GoogleSignIn from "../components/GoogleSignIn";
import "../styles/dashboard.css";

export default function Login() {
  const { login, loginWithGoogle } = useAuth();
  const host = institutionHost();
  const [institution, setInstitution] = useState(null);
  const [profileError, setProfileError] = useState("");
  const [profileLoading, setProfileLoading] = useState(Boolean(host));
  const [profileAttempt, setProfileAttempt] = useState(0);
  usePageTitle("Sign in", institution?.name);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const portalReady = !host || Boolean(institution);

  useEffect(() => {
    if (!host) return;
    let active = true;
    setProfileLoading(true);
    setProfileError("");
    apiFetch("/institutions/login-profile").then((profile) => {
      if (active) setInstitution(profile);
    }).catch((err) => {
      if (active) { setInstitution(null); setProfileError(err.message); }
    }).finally(() => { if (active) setProfileLoading(false); });
    return () => { active = false; };
  }, [host, profileAttempt]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!portalReady || profileLoading || submitting) return;
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page brand-login">
      <section className="login-art">
        <BrandLogo inverse />
        <div><h1>Every institution.<br /><em>One learning space.</em></h1><p className="login-art-description">Classes, coursework and academic progress. Connected in a space your institution can call its own.</p></div>
        <div className="login-art-footer">{brand.tagline}</div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <BrandLogo />
          {institution?.logo_url && <img className="institution-logo-preview" src={institution.logo_url} alt={`${institution.name} logo`} referrerPolicy="no-referrer" />}
          <h2>{institution ? `Welcome to ${institution.name}` : host ? "Institution sign in" : "Welcome back"}</h2>
          <p>{institution ? `Sign in with your @${institution.email_domain} account.` : host ? host : "Sign in with your institution account."}</p>
          {profileLoading && <p role="status">Loading your institution…</p>}
          {profileError && <div className="error-banner" role="alert"><p>{profileError}</p><button type="button" className="btn btn-secondary" onClick={() => setProfileAttempt((value) => value + 1)}>Try again</button></div>}
          {portalReady && !profileLoading && <>
          <form onSubmit={handleSubmit} className="login-form">
            <label className="field-label">Institution email<input className="field" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder={institution ? `you@${institution.email_domain}` : "you@institution.edu"} required autoComplete="email" /></label>
            <label className="field-label">Password<input className="field" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required autoComplete="current-password" /></label>
            <Link className="forgot-password-link" to="/forgot-password">Forgot password?</Link>
            {error && <p className="error-banner">{error}</p>}
            <button type="submit" disabled={submitting} className="btn btn-primary">{submitting ? "Signing in…" : "Sign in"}</button>
          </form>
          <GoogleSignIn emailDomain={institution?.email_domain} disabled={submitting} onCredential={async (credential, nonce) => {
            setSubmitting(true); setError("");
            try { await loginWithGoogle(credential, nonce); }
            finally { setSubmitting(false); }
          }} />
          </>}
          <p className="auth-switch">Students and staff: contact your institution administrator for an account.</p>
          {!host && <div className="institution-invite"><strong>Bring your institution here.</strong><Link to="/register-institution">Register your institution <span aria-hidden="true">↗</span></Link></div>}
        </div>
      </section>
    </main>
  );
}
