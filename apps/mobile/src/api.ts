export type Dashboard = {
  kpis: { id: string; label: string; formatted: string; delta: string }[];
  approvals: { id: string; title: string; affected_users: number; budget: number; evidence_tier: string; status: string }[];
  campaigns: { id: string; name: string; status: string; goal: string; expected_lift: string }[];
};

declare const process: { env: Record<string, string | undefined> };

const configuredBase = process.env.EXPO_PUBLIC_GROWTHEVO_API?.trim().replace(/\/+$/, "");
const base = configuredBase || "http://127.0.0.1:8765";
const REQUEST_TIMEOUT_MS = 10_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      signal: init?.signal ?? controller.signal,
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 600);
      throw new Error(`GrowthEvo API ${response.status}: ${detail}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`GrowthEvo API request timed out after ${REQUEST_TIMEOUT_MS}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function getDashboard(): Promise<Dashboard> {
  return request<Dashboard>("/api/v1/dashboard");
}

export function approve(
  id: string,
  decision: "approve_5" | "approve_25" | "reject",
): Promise<Record<string, unknown>> {
  return request(`/api/v1/approvals/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, note: "Reviewed from GrowthEvo Mobile" }),
  });
}
