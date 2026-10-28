# FrameFlow authentication backend

From this folder:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

In another terminal, start the frontend with `npm.cmd run dev` from `lens-ledger-studio-hub`. Set `VITE_API_URL` to the backend origin if it is not `http://127.0.0.1:8000`.

Registration sends an email verification link. After verification and login, studio setup requires a studio name; the other studio details are optional. The trial starts through a separate endpoint without a plan or payment details.

For deployment, set `DJANGO_DEBUG=false`, a unique `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, and `VITE_API_URL`. Serve both apps over HTTPS. Configure a shared cache for DRF throttling when running more than one backend process.

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register/` | Create an inactive account and email a verification link |
| GET | `/api/auth/verify-email/?token=...` | Verify the email and return to login |
| GET/POST/PATCH | `/api/auth/studio/` | Read, create, or update the studio |
| POST | `/api/auth/trial/start/` | Start the 14-day trial; safe to call again |
| POST | `/api/auth/login/` | Return a DRF auth token after verification |
| GET | `/api/auth/me/` | Return the current user (`Authorization: Token ...`) |
| POST | `/api/auth/logout/` | Revoke the current token |

Run API tests with `python manage.py test accounts`.
