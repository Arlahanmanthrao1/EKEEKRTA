import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import { useAuth } from "../../context/AuthContext";

export default function InstitutionProfile() {
  const { refreshUser } = useAuth();
  const [form, setForm] = useState(null);
  const [domain, setDomain] = useState("");
  const [institutionType, setInstitutionType] = useState("university");
  const [loginAddress, setLoginAddress] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { apiFetch("/institutions/current").then((value) => {
    setDomain(value.email_domain);
    setInstitutionType(value.institution_type || "university");
    setForm({ name: value.name, email: value.email || "", logo_url: value.logo_url || "", address: value.address || "" });
  }).catch((err) => setError(err.message)); }, []);
  useEffect(() => { apiFetch("/institutions/current/login-address").then(setLoginAddress).catch((err) => setError(err.message)); }, []);
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setSaved(false);
    try {
      await apiFetch("/institutions/current", { method: "PATCH", body: JSON.stringify({ ...form, logo_url: form.logo_url || null, address: form.address || null }) });
      await refreshUser();
      setSaved(true);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return <section className="card panel-card"><h2 className="section-title">Institution profile</h2>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {!form ? <p>Loading institution profile…</p> : <>
      <p>Registered email domain: <strong>@{domain}</strong>. All accounts belong to this institution.</p>
      <p>Institution type: <strong>{institutionType === "training_institution" ? "Training institution" : "University"}</strong>. This selection controls which institution-level integrations are available.</p>
      {loginAddress && <div className="institution-login-address">
        <h3>Institution login address</h3><code>{loginAddress.url}</code>
        <p>{loginAddress.configured ? "Configured in EKEEKRTA. Your domain administrator must also complete the hosting and DNS setup; this status does not check public availability." : "Not connected yet. Ask your domain administrator to connect this address, then have the platform operator enable your institution portal."}</p>
      </div>}
      {form.logo_url && <img className="institution-logo-preview" src={form.logo_url} alt={`${form.name} logo`} referrerPolicy="no-referrer" />}
      <form className="form-grid" onSubmit={submit}>
        {[["name", "Institution name", "text"], ["email", "Official contact email", "email"], ["logo_url", "Logo — hosted HTTPS image URL", "url"], ["address", "Address", "text"]].map(([key, label, type]) => <label className="field-label" key={key}>{label}<input className="field" type={type} value={form[key]} required={key === "name" || key === "email"} onChange={(event) => { setSaved(false); setForm({ ...form, [key]: event.target.value }); }} /></label>)}
        {saved && <p className="success-banner wide" role="status">Institution details saved.</p>}
        <div className="wide"><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save institution details"}</button></div>
      </form></>}
  </section>;
}
