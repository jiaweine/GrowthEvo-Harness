# GrowthEvo Mobile

Expo / React Native companion for the GrowthEvo Growth OS.

The mobile surface deliberately focuses on workflows that benefit from a phone: executive incremental KPI checks, campaign health and evidence-aware approvals. Deep experiment authoring, policy debugging and trace inspection remain desktop-first.

## Run

Start the API first from the repository root:

```bash
pip install -e '.[web]'
growthevo-web --host 0.0.0.0
```

Then:

```bash
cd apps/mobile
npm install
EXPO_PUBLIC_GROWTHEVO_API=http://YOUR-LAN-IP:8765 npm start
```

Use an HTTPS endpoint for production builds. Approval mutations call the same `/api/v1/approvals/*` contract as the web client, so auth/RBAC/audit adapters can be added once at the API boundary.
