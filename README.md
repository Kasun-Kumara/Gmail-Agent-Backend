# Gmail AI Agent API

FastAPI backend for the Gmail AI Agent. This directory is a standalone Git repository and can be deployed to Render.

## Deploy to Render

Create a Render Web Service from this repository. Render can use `render.yaml`, or set:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/api/health`

Set these environment variables in Render:

- `GROQ_API_KEY`: your Groq API key.
- `FRONTEND_ORIGINS`: the deployed Vercel origin, such as `https://your-app.vercel.app`. Add custom domains as comma-separated origins. For local development, include `http://localhost:5173` if needed.
- `GMAIL_TOKEN_JSON`: the contents of an authorized Google `token.json` file. Create/refresh the OAuth token locally first. Keep this value private. The token must have the Gmail modify scope used by this application.

The API uses a persistent OAuth refresh token to refresh access. Render's filesystem is ephemeral, so do not rely on a locally uploaded `token.json` surviving deploys. `credentials.json` is only used for the local interactive OAuth setup; the hosted service expects `GMAIL_TOKEN_JSON` to already be authorized.

## Run locally

Create a virtual environment, install `requirements.txt`, then run from this directory:

```sh
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Put `GROQ_API_KEY` in a `.env` file here. For Gmail, place your OAuth client file at `credentials.json` and authorize once locally to create `token.json`.
