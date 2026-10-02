import { useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { BrandLogo, usePageTitle } from "../branding/Brand";
import "../styles/dashboard.css";

const MAX_LOGO_SOURCE_BYTES = 5 * 1024 * 1024;
const MAX_STORED_LOGO_LENGTH = 1950;
const LOGO_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function loadLogoImage(file) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const objectUrl = URL.createObjectURL(file);
    image.onload = () => { URL.revokeObjectURL(objectUrl); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error("The selected logo could not be read.")); };
    image.src = objectUrl;
  });
}

export async function prepareInstitutionLogo(file) {
  if (!file || !LOGO_TYPES.has(file.type)) throw new Error("Choose a PNG, JPEG, or WebP image.");
  if (file.size > MAX_LOGO_SOURCE_BYTES) throw new Error("Choose a logo smaller than 5 MB.");
  const image = await loadLogoImage(file);
  for (const size of [160, 128, 96, 80, 64]) {
    const scale = Math.min(1, size / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    for (const quality of [.82, .68, .52]) {
      const webp = canvas.toDataURL("image/webp", quality);
      if (webp.startsWith("data:image/webp") && webp.length <= MAX_STORED_LOGO_LENGTH) return webp;
      const jpeg = canvas.toDataURL("image/jpeg", quality);
      if (jpeg.length <= MAX_STORED_LOGO_LENGTH) return jpeg;
    }
  }
  throw new Error("This logo is too detailed to optimize. Choose a simpler image or use a hosted HTTPS image link.");
}

export default function InstitutionRegistration() {
  usePageTitle("Register your institution");
  const [form, setForm] = useState({ institution_type: "", name: "", email: "", logo_url: "", address: "", adminName: "", adminEmail: "", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [created, setCreated] = useState(null);
  const update = (event) => setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  const uploadLogo = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(""); setLogoBusy(true);
    try {
      const logoUrl = await prepareInstitutionLogo(file);
      setForm((current) => ({ ...current, logo_url: logoUrl }));
    }
    catch (err) { setError(err.message); }
    finally { setLogoBusy(false); event.target.value = ""; }
  };
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (form.password !== form.confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      const account = await apiFetch("/institutions/register", { method: "POST", body: JSON.stringify({
        institution: { institution_type: form.institution_type, name: form.name, email: form.email, logo_url: form.logo_url || null, address: form.address || null },
        administrator: { name: form.adminName, email: form.adminEmail, password: form.password },
      }) });
      setCreated(account);
      setForm((current) => ({ ...current, password: "", confirm: "" }));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return <main className="onboarding-page">
    <header className="brand-onboarding-header"><Link className="platform-home" to="/login"><BrandLogo /></Link><Link to="/login">← Back to sign in</Link></header>
    <section className="card panel-card">
      <p className="section-eyebrow">Institution onboarding</p><h1>Register your institution</h1>
      {created ? <div role="status"><h2>{created.institution.name} was submitted for review</h2><p>The Ekeekrta team must approve this institution before {created.email} can sign in. Your chosen administrator password remains valid; Ekeekrta staff cannot view it.</p><p className="footnote">You can return to sign in after approval. Suspicious or unauthorized registrations may be rejected.</p><Link className="btn btn-primary" to="/login">Return to sign in</Link></div> : <>
        <p>Create an institution profile and its first administrator. Students and staff accounts are created by the administrator after setup.</p>
        <p className="footnote">Use your official institution email domain. Only register an institution you are authorized to administer. Domain ownership is not automatically verified in this version.</p>
        <form className="form-grid" onSubmit={submit}>
          <h2 className="wide">1. Institution details</h2>
          <fieldset className="wide institution-type-fieldset">
            <legend>Institution type</legend>
            <div className="institution-type-options">
              <label className={`institution-type-card ${form.institution_type === "university" ? "selected" : ""}`}>
                <input type="radio" name="institution_type" value="university" checked={form.institution_type === "university"} onChange={update} required />
                <span><strong>University</strong><small>Academic departments, cohorts, semester progression, and optional ERP integration.</small></span>
              </label>
              <label className={`institution-type-card ${form.institution_type === "training_institution" ? "selected" : ""}`}>
                <input type="radio" name="institution_type" value="training_institution" checked={form.institution_type === "training_institution"} onChange={update} required />
                <span><strong>Training institution</strong><small>Courses, classes, assignments, quizzes, attendance, programming assessments, and AI—without ERP integration.</small></span>
              </label>
            </div>
          </fieldset>
          <label className="field-label">Institution name<input className="field" name="name" value={form.name} onChange={update} minLength={2} maxLength={160} required /></label>
          <label className="field-label">Official institution email<input className="field" type="email" name="email" value={form.email} onChange={update} required /><small>This email’s domain will be required for staff and student accounts.</small></label>
          <div className="field-label institution-logo-upload"><span>Institution logo</span><label className="logo-file-button"><input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadLogo} disabled={busy || logoBusy} /><span>{logoBusy ? "Optimizing logo…" : "Choose logo image"}</span></label><small>PNG, JPEG, or WebP up to 5 MB. The image is optimized for the portal and saved with the institution profile.</small></div>
          <label className="field-label">Or use a hosted HTTPS logo URL<input className="field" type="url" name="logo_url" value={form.logo_url.startsWith("data:image/") ? "" : form.logo_url} onChange={update} placeholder="https://…" /></label>
          {form.logo_url && <div className="institution-logo-selection"><img className="institution-logo-preview" src={form.logo_url} alt="Institution logo preview" referrerPolicy="no-referrer" /><button className="btn btn-soft" type="button" onClick={() => setForm((current) => ({ ...current, logo_url: "" }))} disabled={busy || logoBusy}>Remove logo</button></div>}
          <label className="field-label">Address<input className="field" name="address" value={form.address} onChange={update} maxLength={500} /></label>
          <h2 className="wide">2. Administrator profile</h2>
          <label className="field-label">Administrator name<input className="field" name="adminName" value={form.adminName} onChange={update} minLength={2} maxLength={120} required autoComplete="name" /></label>
          <label className="field-label">Administrator email<input className="field" type="email" name="adminEmail" value={form.adminEmail} onChange={update} required autoComplete="email" /><small>Must use the same institution domain.</small></label>
          <label className="field-label">Password<input className="field" type="password" name="password" value={form.password} onChange={update} minLength={12} maxLength={72} required autoComplete="new-password" /></label>
          <label className="field-label">Confirm password<input className="field" type="password" name="confirm" value={form.confirm} onChange={update} minLength={12} maxLength={72} required autoComplete="new-password" /></label>
          <p className="footnote wide">Use at least 12 characters. No email containing credentials will be sent.</p>
          {error && <p className="error-banner wide" role="alert">{error}</p>}
          <div className="wide"><button className="btn btn-primary" disabled={busy || logoBusy}>{busy ? "Creating institution…" : logoBusy ? "Preparing logo…" : "Create institution and administrator"}</button></div>
        </form>
      </>}
    </section>
  </main>;
}
