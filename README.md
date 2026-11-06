# FrameFlow authentication backend

From this folder:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

In another terminal, start the frontend with `npm.cmd run dev` from `lens-ledger-studio-hub`. Set `VITE_API_URL` to the backend origin if it is not `http://127.0.0.1:8000`.

Registration sends an email verification link. After verification and login, studio setup requires a studio name; the other studio details are optional. The trial starts through a separate endpoint without a plan or payment details. It lasts `BILLING_TRIAL_DAYS` (15). When it ends the workspace is read-only (writes return HTTP 402) until a plan is bought with Razorpay. Plans are managed in Django admin. Setup: see `../RAZORPAY_SETUP.md`.

For deployment, set `DJANGO_DEBUG=false`, a unique `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, and `VITE_API_URL`. Serve both apps over HTTPS. Configure a shared cache for DRF throttling when running more than one backend process.

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register/` | Create an inactive account and email a verification link |
| GET | `/api/auth/verify-email/?token=...` | Verify the email and return to login |
| GET/POST/PATCH | `/api/auth/studio/` | Read, create, or update the studio |
| POST | `/api/auth/trial/start/` | Start the free trial; safe to call again |
| POST | `/api/auth/login/` | Return a DRF auth token after verification |
| GET | `/api/auth/me/` | Return the current user (`Authorization: Token ...`) |
| POST | `/api/auth/logout/` | Revoke the current token |
| GET/POST | `/api/auth/quotes/` | List shared quote decisions or publish a quote snapshot (authenticated) |
| GET/POST | `/api/auth/quotes/<uuid>/` | View a published quote or accept/reject it from the client portal |
| POST | `/api/auth/documents/email/` | Email a generated invoice or receipt PDF to a client (authenticated) |
| GET | `/api/billing/plans/` | Public list of active plans, trial length and GST rate |
| GET | `/api/billing/subscription/` | Current studio's trial/plan state, days left, access |
| POST | `/api/billing/checkout/` | Create a Razorpay order for `{plan, billing_cycle}` |
| POST | `/api/billing/verify/` | Verify Razorpay's payment signature and activate the plan |
| GET | `/api/billing/payments/` | Billing history |
| POST | `/api/billing/webhooks/razorpay/` | Razorpay webhook (signed); confirms payments server-side |

The core studio workspace currently stores catalogue, enquiries, clients, bookings and payment records in browser localStorage. Published quotations and client decisions are stored in the backend. Deploy both apps and run `python manage.py migrate` before sharing client links across devices.

Run API tests with `python manage.py test accounts billing`.

Send trial/renewal reminder emails once a day with `python manage.py send_billing_reminders`.
