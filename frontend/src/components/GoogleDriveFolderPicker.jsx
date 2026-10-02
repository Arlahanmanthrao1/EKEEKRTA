import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";

const pickerKey = import.meta.env?.VITE_GOOGLE_PICKER_API_KEY || "";
const driveAppId = import.meta.env?.VITE_GOOGLE_DRIVE_APP_ID || "";

function loadPicker() {
  return new Promise((resolve, reject) => {
    const ready = () => window.gapi.load("picker", { callback: resolve, onerror: reject });
    if (window.gapi) return ready();
    const existing = document.querySelector('script[data-ekeekrta-google-api="true"]');
    if (existing) {
      existing.addEventListener("load", ready, { once: true });
      existing.addEventListener("error", reject, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.dataset.ekeekrtaGoogleApi = "true";
    script.onload = ready;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

export default function GoogleDriveFolderPicker({ value, onChange }) {
  const [status, setStatus] = useState(null);
  const [selectedName, setSelectedName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadStatus = () => apiFetch("/integrations/google-drive/status").then(setStatus).catch((err) => setError(err.message));
  useEffect(() => { loadStatus(); }, []);

  const connect = async () => {
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/integrations/google-drive/connect", { method: "POST" });
      window.location.assign(result.authorization_url);
    } catch (err) { setError(err.message); setBusy(false); }
  };

  const chooseFolder = async () => {
    if (!pickerKey || !driveAppId) {
      setError("The operator must configure the Google Picker API key and Drive app ID.");
      return;
    }
    setBusy(true); setError("");
    try {
      const token = await apiFetch("/integrations/google-drive/access-token", { method: "POST" });
      await loadPicker();
      const view = new window.google.picker.DocsView(window.google.picker.ViewId.FOLDERS)
        .setIncludeFolders(true).setSelectFolderEnabled(true);
      const picker = new window.google.picker.PickerBuilder()
        .setOAuthToken(token.access_token).setDeveloperKey(pickerKey).setAppId(driveAppId)
        .addView(view).setTitle("Choose the recording folder for this batch")
        .setCallback(async (data) => {
          if (data.action === window.google.picker.Action.PICKED) {
            const folder = data.docs[0];
            try {
              const checked = await apiFetch("/integrations/google-drive/validate-folder", {
                method: "POST", body: JSON.stringify({ folder_id: folder.id }),
              });
              onChange(checked.id); setSelectedName(checked.name);
            } catch (err) { setError(err.message); }
          }
          if (data.action === window.google.picker.Action.PICKED || data.action === window.google.picker.Action.CANCEL) setBusy(false);
        }).build();
      picker.setVisible(true);
    } catch (err) { setError(err.message || "Could not open Google Drive"); setBusy(false); }
  };

  if (!status) return <p className="footnote">Checking your personal Google Drive connection…</p>;
  return <div className="card" style={{ padding: 16 }}>
    <strong>Personal Google Drive</strong>
    {!status.oauth_configured && <p className="error-banner">Google Drive OAuth is not configured by the Ekeekrta operator.</p>}
    {status.connected
      ? <><p className="footnote">Connected as {status.google_email}. Only the folder you choose is used for this batch.</p>
          <button className="btn btn-secondary" type="button" disabled={busy} onClick={chooseFolder}>{busy ? "Opening Drive…" : "Choose folder from My Drive"}</button>
          {value && <p className="success-banner" style={{ marginTop: 10 }}>Selected: {selectedName || "Google Drive folder"}</p>}</>
      : <><p className="footnote">Connect the trainer's own Google account before selecting a recording folder.</p>
          <button className="btn btn-secondary" type="button" disabled={busy || !status.oauth_configured} onClick={connect}>{busy ? "Opening Google…" : "Connect my Google Drive"}</button></>}
    {error && <p className="error-banner" style={{ marginTop: 10 }}>{error}</p>}
  </div>;
}
