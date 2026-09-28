export type Dashboard = {
  kpis: { id: string; label: string; formatted: string; delta: string }[];
  approvals: { id: string; title: string; affected_users: number; budget: number; evidence_tier: string; status: string }[];
  campaigns: { id: string; name: string; status: string; goal: string; expected_lift: string }[];
};

const base = process.env.EXPO_PUBLIC_GROWTHEVO_API ?? "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export function getDashboard(): Promise<Dashboard> {
  return request<Dashboard>("/api/v1/dashboard");
}

export function approve(
  id: string,
  decision: "approve_5" | "approve_25" | "reject",
): Promise<Record<string, unknown>> {
  return request(`/api/v1/approvals/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, note: "Reviewed from GrowthEvo Mobile" }),
  });
}
