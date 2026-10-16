"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, Suspense, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { logout as signOut } from "../../lib/auth";
import type { EstateModel } from "./types";

const RANGES = [
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "mtd", label: "This month" },
  { id: "qtr", label: "This quarter" },
];

interface ConsoleValue {
  model: EstateModel | null;
  projectId: string;
  rangeId: string;
  loading: boolean;
  error: string;
  selectProject: (id: string) => void;
  selectRange: (id: string) => void;
  refresh: () => void;
  switchOrg: (orgId: string) => Promise<void>;
}

const ConsoleContext = createContext<ConsoleValue | null>(null);

export function useConsole(): ConsoleValue {
  const value = useContext(ConsoleContext);
  if (!value) throw new Error("useConsole must be used inside the live shell");
  return value;
}

function ConsoleProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState("");
  const [rangeId, setRangeId] = useState("mtd");
  const [nonce, setNonce] = useState(0);
  const fresh = useRef(false);
  const [model, setModel] = useState<EstateModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const isFresh = fresh.current;
    fresh.current = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ range: rangeId });
        if (projectId) params.set("projectId", projectId);
        if (isFresh) params.set("fresh", "1");
        const response = await fetch(`/api/estate?${params}`, { cache: "no-store", credentials: "include" });
        const body = (await response.json().catch(() => ({}))) as EstateModel & { detail?: string };
        if (cancelled) return;
        if (response.status === 401) {
          window.location.href = "/login/";
          return;
        }
        if (!response.ok) {
          setError(body.detail || body.message || "Azure could not be read.");
          return;
        }
        setModel(body);
      } catch {
        if (!cancelled) setError("The network request failed.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, rangeId, nonce]);

  const value: ConsoleValue = {
    model,
    projectId: model?.project?.id || projectId,
    rangeId,
    loading,
    error,
    selectProject: (id) => {
      if (id && id !== projectId) setProjectId(id);
    },
    selectRange: (id) => {
      if (id && id !== rangeId) setRangeId(id);
    },
    refresh: () => {
      fresh.current = true;
      setNonce((item) => item + 1);
    },
    switchOrg: async (orgId) => {
      const response = await fetch("/api/session/org", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orgId }),
      });
      if (!response.ok) {
        setError("Could not switch organization.");
        return;
      }
      setProjectId("");
      setModel(null);
      fresh.current = true;
      setNonce((item) => item + 1);
    },
  };

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>;
}

const NAV: Array<
  | { section: string }
  | { href: string; label: string }
  | { id: string; label: string; children: Array<{ href: string; label: string }> }
> = [
  { href: "/dashboard", label: "Dashboard" },
  { section: "Estate" },
  { href: "/vms", label: "Virtual machines" },
  { href: "/containers", label: "App hosting" },
  {
    id: "data",
    label: "Data platform",
    children: [
      { href: "/databricks", label: "Workspace" },
      { href: "/lakes", label: "Lakes" },
      { href: "/pipelines", label: "Pipelines" },
    ],
  },
  {
    id: "resources",
    label: "Resources",
    children: [
      { href: "/resources", label: "All" },
      { href: "/resources?kind=vm", label: "Virtual machines" },
      { href: "/resources?kind=database", label: "Databases" },
      { href: "/resources?kind=storage", label: "Storage" },
      { href: "/resources?kind=cdn", label: "CDN" },
      { href: "/resources?kind=serverless", label: "Functions" },
    ],
  },
  { section: "Control" },
  { href: "/costs", label: "Costs & billing" },
  { href: "/alerts", label: "Alerts" },
  { href: "/insights", label: "Advisor" },
  { href: "/settings", label: "Organization" },
  { section: "Workspace" },
  { href: "/", label: "Chat" },
  { href: "/wiki", label: "Wiki" },
  { href: "/dashboard/findings", label: "Findings" },
  { href: "/dashboard/workflows", label: "Workflows" },
  { href: "/dashboard/approvals", label: "Approvals" },
  { href: "/dashboard/break-glass", label: "Break-glass" },
  { href: "/dashboard/architecture", label: "Architecture" },
  { href: "/dashboard/engineering", label: "Engineering" },
];

function active(href: string, pathname: string, search: URLSearchParams): boolean {
  const [path, query] = href.split("?");
  const current = pathname.replace(/\/$/, "") || "/";
  if (current !== (path || "/")) return false;
  if (!query) return !search.get("kind");
  const want = new URLSearchParams(query);
  for (const [key, value] of want.entries()) {
    if (search.get(key) !== value) return false;
  }
  return true;
}

function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const search = useSearchParams();
  const router = useRouter();
  const { model, rangeId, loading, error, selectProject, selectRange, refresh, switchOrg } = useConsole();
  const [open, setOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const workspace = model?.workspace;
  const projects = workspace?.projects || [];
  const project = projects.find((item) => item.id === model?.project?.id) || projects[0];
  const currentPath = pathname.replace(/\/$/, "") || "/";
  const setupPaths = new Set(["/dashboard", "/vms", "/containers", "/databricks", "/lakes", "/pipelines", "/resources", "/costs", "/alerts", "/insights"]);
  const showSetup = model?.status === "setup" && setupPaths.has(currentPath);

  useEffect(() => {
    setOpen(false);
  }, [pathname, search]);

  return (
    <div className="min-h-screen bg-[#f7f6f4] text-[#232323]">
      {open ? (
        <button type="button" aria-label="Close menu" className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setOpen(false)} />
      ) : null}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col bg-[#f6f6f6] px-3 pb-4 ${open ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0`}>
        <div className="flex h-[72px] items-center gap-2.5 border-b border-[#e4e4e4] px-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#E2773C] text-sm font-bold text-white">IF</span>
          <div>
            <div className="text-[15px] font-bold leading-none">Infralens</div>
            <div className="mt-1 truncate text-[11px] text-[#717171]">{workspace?.org?.name || "Azure"}</div>
          </div>
        </div>
        <nav aria-label="Estate" className="mt-3 flex-1 space-y-1 overflow-y-auto">
          {NAV.map((item) => {
            if ("section" in item) {
              return (
                <div key={item.section} className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#717171]">
                  {item.section}
                </div>
              );
            }
            if ("children" in item) {
              return (
                <div key={item.id} className="px-3 py-1 text-sm font-semibold">
                  <div>{item.label}</div>
                  <div className="ml-2 mt-1 space-y-0.5 border-l border-[#e4e4e4] pl-2">
                    {item.children.map((child) => (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={`block rounded-xl px-3 py-1.5 ${active(child.href, pathname, search) ? "bg-orange-50 font-semibold shadow-[inset_3px_0_0_#E2773C]" : "text-[#5f5f5f]"}`}
                      >
                        {child.label}
                      </Link>
                    ))}
                  </div>
                </div>
              );
            }
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center rounded-xl px-3 py-2 text-sm font-semibold ${active(item.href, pathname, search) ? "bg-orange-50 shadow-[inset_3px_0_0_#E2773C]" : "text-[#5f5f5f]"}`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="lg:pl-[280px]">
        <header className="sticky top-0 z-20 flex h-[72px] items-center gap-2 border-b border-[#e7e5e4] bg-[#f7f6f4]/90 px-4">
          <button type="button" className="rounded-xl border border-[#e7e5e4] px-3 py-2 text-sm lg:hidden" onClick={() => setOpen(true)}>
            Menu
          </button>
          <label className="text-sm">
            <span className="sr-only">Project</span>
            <select
              className="rounded-2xl border border-[#e7e5e4] bg-white px-3 py-2"
              value={project?.id || ""}
              onChange={(event) => selectProject(event.target.value)}
            >
              {projects.length === 0 ? <option value="">No project</option> : null}
              {projects.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="hidden items-center gap-1 rounded-2xl bg-[#f6f6f6] p-1 md:flex" role="group" aria-label="Cost range">
            {RANGES.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => selectRange(item.id)}
                className={`rounded-xl px-2.5 py-1.5 text-xs font-semibold ${item.id === rangeId ? "bg-white" : "text-[#717171]"}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button type="button" onClick={refresh} className="rounded-full border border-[#e7e5e4] px-3 py-1.5 text-xs font-semibold">
              {loading ? "Reading Azure…" : "Refresh"}
            </button>
            <button type="button" aria-label="Account menu" onClick={() => setUserOpen((value) => !value)} className="grid h-9 w-9 place-items-center rounded-full bg-[#232323] text-xs font-bold text-white">
              {(workspace?.user?.name || "U").slice(0, 1)}
            </button>
            {userOpen ? (
              <div className="absolute right-4 top-16 z-30 w-64 rounded-2xl border border-[#e7e5e4] bg-white p-3">
                <div className="text-sm font-semibold">{workspace?.user?.name}</div>
                <div className="text-xs text-[#717171]">{workspace?.orgRole}</div>
                {(workspace?.orgs || []).map((org) => (
                  <button key={org.id} type="button" className="mt-1 block w-full text-left text-xs" onClick={() => void switchOrg(org.id)}>
                    {org.name}
                  </button>
                ))}
                <button
                  type="button"
                  className="mt-3 text-sm font-semibold text-[#E2773C]"
                  onClick={() => {
                    signOut();
                    router.push("/login/");
                  }}
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </header>
        <main className="px-4 py-5 sm:px-6">
          {error ? <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
          {showSetup ? <SetupCard message={model?.message || "Map an Azure connection to this project."} /> : children}
        </main>
      </div>
    </div>
  );
}

function SetupCard({ message }: { message: string }) {
  return (
    <section className="mx-auto max-w-2xl rounded-2xl border border-[#e7e5e4] bg-white p-6">
      <h1 className="text-2xl font-semibold">Connect this organization to Azure</h1>
      <p className="mt-2 text-sm text-[#717171]">{message}</p>
      <Link href="/settings" className="mt-5 inline-flex h-11 items-center rounded-2xl bg-[#E2773C] px-4 text-sm font-semibold text-white">
        Open organization settings
      </Link>
    </section>
  );
}

export function LiveFrame({ children }: { children: ReactNode }) {
  return (
    <ConsoleProvider>
      <Suspense fallback={<p className="p-6 text-sm text-[#717171]">Opening the workspace…</p>}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </ConsoleProvider>
  );
}
