# Northstar Android app

## Local development

1. Start the FastAPI backend from `backend` so the Android emulator can reach it:

   ```powershell
   python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. In Windows, enable **Settings → System → For developers → Developer Mode** if Flutter reports that plugin builds require symlink support.
3. From `mobile`, fetch the Flutter dependencies and run on the emulator:

   ```powershell
   flutter pub get
   flutter run -d emulator-5554 --dart-define=API_BASE_URL=http://10.0.2.2:8000
   ```

For a physical Android phone, replace `10.0.2.2` with the computer's LAN IP address and keep both devices on the same network.

To run the same app in Chrome, start the backend with `CORS_ORIGINS` containing the exact web origin, then run:

```powershell
flutter run -d chrome --web-port 7357 --dart-define=API_BASE_URL=http://localhost:8000
```

The backend's example CORS list includes `http://localhost:7357` and `http://127.0.0.1:7357`. Use the same host in the browser and API URL (both `localhost` or both `127.0.0.1`) so the browser treats the session cookie consistently. For other Flutter web ports, add that exact origin to `CORS_ORIGINS` in `backend/.env` and restart the backend.

## Features

- Account registration, sign-in, session validation, and sign-out.
- Northeast state place search and primary/alternative route calculations.
- Route risk and weather summaries, vehicle and incident markers, and OpenStreetMap map display.
- On-demand NASA COOLR reported landslides and LHASA regional hazard overlay.
- Incident reporting with optional camera/gallery photo, automatic current GPS coordinates, and editable latitude/longitude.

Photo reports are stored in `backend/uploads/incidents` and served through an authenticated API endpoint. Keep this directory on persistent storage in a deployed environment; local container filesystems may be temporary.

Use an HTTPS `API_BASE_URL` for production builds. The cleartext HTTP setting is included in the Android debug manifest only.
