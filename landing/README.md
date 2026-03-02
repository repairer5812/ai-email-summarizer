# webmail-summary landing

This folder contains the marketing landing page built with Next.js + shadcn/ui.

## Local Development

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Build

```bash
npm run build
npm run start
```

## Deploy to Vercel

1. Import this repository in Vercel.
2. Set **Root Directory** to `landing`.
3. Keep build command as `next build`.
4. Set production domain (example): `webmail-summary.vercel.app`.

## Content Notes

- Download button points to GitHub Releases latest page.
- If domain changes, update:
  - `app/robots.ts`
  - `app/sitemap.ts`
