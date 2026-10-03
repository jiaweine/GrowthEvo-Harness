# GrowthEvo Mobile

Expo / React Native companion for the GrowthEvo Growth OS.

The mobile surface deliberately focuses on workflows that benefit from a phone: executive incremental KPI checks, campaign health and evidence-aware approvals. Deep experiment authoring, policy debugging and trace inspection remain desktop-first.

## Compatibility contract

The mobile app intentionally stays on the Expo SDK 57 compatibility line: React 19.2.x, React Native 0.86.x and TypeScript 6.x. Patch updates inside those supported lines are welcome; crossing to a newer React, React Native or TypeScript line must happen together with an intentional Expo SDK migration and the repository's native/mobile validation, rather than as an isolated dependency bump.

GrowthEvo keeps a single product identity. The application manifest and lockfile root package therefore remain `1.0.0`; dependency package versions remain ordinary technical metadata and are not GrowthEvo product generations.

## Run

Start the API first from the repository root:

```bash
pip install -e '.[web]'
growthevo-web --host 0.0.0.0
```

Then, for local development:

```bash
cd apps/mobile
npm ci
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```

Cleartext HTTP is accepted only by React Native development builds (`__DEV__`). Production builds require `EXPO_PUBLIC_GROWTHEVO_API` to be configured and to use HTTPS; a missing endpoint or a production `http://` endpoint fails closed rather than silently using the simulator fallback.

Approval mutations call the same stable `/api/approvals/*` contract as the web client, so auth/RBAC/audit adapters can be added once at the API boundary.
