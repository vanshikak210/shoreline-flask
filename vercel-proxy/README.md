# Shoreline API proxy (Vercel)

School Wi-Fi blocks `onrender.com`, but allows `vercel.app`. This folder deploys a
Vercel project that forwards every request to the Render backend
(`https://shoreline-flask.onrender.com`), so browsers on school Wi-Fi only ever talk
to Vercel.

- No code here: `vercel.json` rewrites `/<anything>` to the same path on Render.
- Cookies keep working: Render sets the login cookie without a Domain, so the browser
  stores it for the Vercel domain.
- Vercel project settings: **Root Directory = `vercel-proxy`**, Framework = Other,
  no build command.
- The site picks this URL in `assets/js/shoreline/auth.js` (`SHORELINE_BACKENDS`).
