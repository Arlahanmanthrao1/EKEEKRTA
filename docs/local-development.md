# Local development

These steps create an isolated development environment. They do not use or modify the hosted production database unless you deliberately replace the example database URL.

## Prerequisites

- Windows 11, Linux or macOS
- Git
- Python 3.12
- Node.js 20 or newer with npm
- Optional external accounts only for the integrations you want to test

Do not commit `.env`, database, private-key, recording or dataset files. The repository contains `.env.example` templates with placeholders only.

## 1. Clone and inspect

```powershell
git clone https://github.com/Arlahanmanthrao1/EKEEKRTA.git
cd EKEEKRTA
git status
```

## 2. Start the application backend

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The default example uses `backend/lms.db`. Visit:

- health: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`

Do not add a trailing backslash after `python.exe`; that opens or misinterprets the executable instead of running the module.

## 3. Start the frontend

Open a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server reads `VITE_API_BASE_URL=http://localhost:8000` from the example configuration.

## 4. Create initial access

The generic login page includes institution registration. Registering an institution creates its first institution administrator in one transaction. Students and staff do not self-register; the administrator provisions them manually or through a reviewed ERP import.

Platform-operator access is separate. Follow [EKEEKRTA operations](../EKEEKRTA_OPERATIONS.md) and ensure the script points to the intended database before creating an operator.

## 5. Run the optional ERP sandbox

Open a third terminal:

```powershell
cd erp-dummy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit only your local `erp-dummy/.env` and replace `ERP_API_TOKEN` with a random value of at least 24 characters. Then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 9000
```

Open `http://127.0.0.1:9000`, enter the token, and use the ERP user forms. In the EKEEKRTA administrator portal configure:

- base URL: `http://127.0.0.1:9000`
- ERP institution ID: the same `ERP_INSTITUTION_ID`
- API token: the same `ERP_API_TOKEN`

See [ERP integration](erp-integration.md) for the contract.

## 6. Optional integrations

Configure only what you are testing:

| Integration | Configuration |
| --- | --- |
| JaaS / Jitsi | `backend/.env`; see [JaaS setup](../backend/JAAS_SETUP.md) |
| Google sign-in | `GOOGLE_CLIENT_ID`; see [Google sign-in setup](../GOOGLE_SIGN_IN_SETUP.md) |
| Trainer Google Drive | Backend OAuth client/secret plus frontend Picker key/app ID |
| Password email | SMTP variables and reset base URL |
| Programming runner | `CODE_RUNNER_URL` and optional API key |
| WhatsApp alerts | ERP Meta credentials, approved utility template and guardian consent |
| Local AI models | Private executable paths only after the documented evaluation gates pass |

Never put secrets in `VITE_` variables: Vite embeds them into public browser assets.

## 7. Tests and builds

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

ERP:

```powershell
cd erp-dummy
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

Frontend checks:

```powershell
cd frontend
node tests\dashboard-pages.cjs
node tests\registration.cjs
node tests\classroom-layout.cjs
node tests\branding-build.cjs
npm run build
```

Integration tests create isolated temporary data. They do not replace browser interaction, provider calls, multi-network meetings, accessibility review or load testing.

## 8. Common issues

### `No module named uvicorn`

Dependencies were installed into a different interpreter. Run installation and Uvicorn with the exact same `.venv\Scripts\python.exe` path.

### The frontend says `Failed to fetch`

Confirm the backend is running, `VITE_API_BASE_URL` is correct, and `ALLOWED_ORIGINS` contains the exact frontend origin. Restart both services after changing environment files.

### ERP connection timeout

`127.0.0.1` is reachable only from the same computer. A public EKEEKRTA backend needs a public HTTPS ERP address. Confirm the sandbox is running and the institution ID/token match exactly.

### A meeting cannot start

The application intentionally has no silent fallback to an unrelated meeting provider. Configure one supported provider on the backend and restart it.
