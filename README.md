# Aquario SIGAA Connector

Private, one-shot HTTP bridge between Aquario and SIGAA UFPB.

This repository does **not** recreate the SIGAA client or its parsers. It uses
[`sigaa-for-ai-agents`](https://github.com/PucaVaz/sigaa-for-ai-agents), created by
**Puca Vaz**, as an immutable Git dependency. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for revision provenance and the license notice.

> [!IMPORTANT]
> This is an unofficial integration. It is not affiliated with, endorsed by, or
> supported by UFPB or SIGAA.

## Privacy boundary

- SIGAA credentials are accepted only by `POST /v1/sync`.
- The connector has no database and does not persist credentials, cookies, HTML, or PDFs.
- A request-local `SigaaClient` session is closed after ordinary success or failure.
- Responses and errors are marked `Cache-Control: no-store`.
- Request validation never echoes input values.
- The Vercel function has a 150-second maximum duration.

The caller may stop waiting while accepted work continues until the connector cap. Stopping the
request does not guarantee cancellation, remote SIGAA logout, or immediate removal of in-memory
credentials before that work ends.

The Aquario application is responsible for recent-user reauthentication, beta access,
rate limiting, atomic persistence of the normalized snapshot, and the user's deletion controls.

## API

`GET /health` is public and returns only service status.

`POST /v1/sync` requires `Authorization: Bearer $CONNECTOR_API_SECRET` and accepts:

```json
{
  "username": "SIGAA username",
  "password": "SIGAA password",
  "expected_matricula": "11-digit Aquario profile registration or null"
}
```

The response is a versioned, normalized academic snapshot. The raw SIGAA response is never
returned.

## Local development

Python 3.12 and Git are required because the upstream dependency is pinned directly to GitHub.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"  # Windows
copy .env.example .env
pytest
```

Run locally with:

```bash
.venv/Scripts/uvicorn api.index:app --reload
```

## Deployment

Deploy as a separate Vercel project and configure `CONNECTOR_API_SECRET` independently in
Preview and Production. Do not expose that secret to the browser or use a `NEXT_PUBLIC_` prefix.

The upstream revision is intentionally pinned. Parser and SIGAA protocol improvements should be
contributed to the original repository first, then adopted here by updating the commit and running
the complete test suite.
