export type Dashboard = {
  kpis: { id: string; label: string; formatted: string; delta: string }[];
  approvals: { id: string; title: string; affected_users: number; budget: number; evidence_tier: string; status: string }[];
  campaigns: { id: string; name: string; status: string; goal: string; expected_lift: string }[];
};

declare const process: { env: Record<string, string | undefined> };
declare const __DEV__: boolean;

function normalizeApiBase(value: string | undefined): string {
  const raw = value?.trim().replace(/\/+$/, "") ?? "";
  if (!raw) {
    if (__DEV__) {
      // Simulator-friendly fallback only. Physical devices must set the LAN/API
      // address explicitly because 127.0.0.1 points back to the phone itself.
      return "http://127.0.0.1:8765";
    }
    throw new Error("EXPO_PUBLIC_GROWTHEVO_API is required outside development");
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("EXPO_PUBLIC_GROWTHEVO_API must be an absolute http(s) URL");
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new Error("EXPO_PUBLIC_GROWTHEVO_API must be an absolute http(s) URL");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("EXPO_PUBLIC_GROWTHEVO_API must not contain credentials, query strings, or fragments");
  }
  if (!__DEV__ && parsed.protocol !== 'https:') {
    throw new Error("production mobile builds require an HTTPS GrowthEvo API");
  }
  return raw;
}

const configuredBase = process.env.EXPO_PUBLIC_GROWTHEVO_API;
const base = normalizeApiBase(configuredBase);
const REQUEST_TIMEOUT_MS = 10_000;

export function getApiBase(): string {
  return base;
}

export function isSimulatorFallback(): boolean {
  return __DEV__ && !configuredBase?.trim();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const upstream = init?.signal;
  const abortFromUpstream = () => controller.abort();
  if (upstream) {
    if (upstream.aborted) controller.abort();
    else upstream.addEventListener("abort", abortFromUpstream, { once: true });
  }
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const headers = new Headers(init?.headers ?? {});
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    if (typeof init?.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 600);
      throw new Error(`GrowthEvo API ${response.status}: ${detail}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      const reason = upstream?.aborted ? "cancelled" : `timed out after ${REQUEST_TIMEOUT_MS}ms`;
      throw new Error(`GrowthEvo API request ${reason}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    if (upstream) upstream.removeEventListener("abort", abortFromUpstream);
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
