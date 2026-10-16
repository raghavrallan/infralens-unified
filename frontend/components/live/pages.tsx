"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { CostBars, DonutLegend, SpendArea, SplitDonut, UsageLines } from "./charts";
import { useConsole } from "./console";
import type { EstateModel } from "./types";

function PageHead({ eyebrow, title, description }: { eyebrow?: string; title: string; description: string }) {
  return (
    <header className="mb-4">
      {eyebrow ? <p className="text-xs font-semibold uppercase tracking-wide text-[#717171]">{eyebrow}</p> : null}
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-[#717171]">{description}</p>
    </header>
  );
}

function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-[#e7e5e4] bg-white p-4">
      {title ? <h2 className="mb-3 text-sm font-semibold">{title}</h2> : null}
      {children}
    </section>
  );
}

function money(value: number | null | undefined, currency: string): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(value);
}

function readyModel(model: EstateModel | null): EstateModel | null {
  if (!model || model.status === "setup") return null;
  return model;
}

export function EstateOverview() {
  const { model } = useConsole();
  const view = readyModel(model);
  if (!view) return null;
  const currency = view.kpis?.currency || "USD";
  const budget = Number(view.project?.budget);
  const forecast = view.kpis?.forecast;
  const delta = Number.isFinite(budget) && forecast != null ? forecast - budget : null;
  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={view.project?.name}
        title="Estate overview"
        description={`${view.range?.label || "This month"} from Azure Cost Management and resource inventory for the subscriptions attached to this project.`}
      />
      {view.warnings?.[0] ? <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm">{view.warnings[0]}</div> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Panel title="Subscriptions"><p className="text-2xl font-semibold">{view.subscriptions?.length || 0}</p></Panel>
        <Panel title="Resources"><p className="text-2xl font-semibold">{view.kpis?.resourceCount || 0}</p><p className="text-xs text-[#717171]">{view.kpis?.groupCount || 0} resource groups</p></Panel>
        <Panel title="Virtual machines"><p className="text-2xl font-semibold">{view.kpis?.vmRunning || 0}</p><p className="text-xs text-[#717171]">{view.kpis?.vmCount || 0} total</p></Panel>
        <Panel title="Advisor"><p className="text-2xl font-semibold">{view.advisor?.length || 0}</p></Panel>
      </div>
      {view.canSeeCost ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Panel title={view.range?.spendLabel || "Spend"}><p className="text-2xl font-semibold">{money(view.kpis?.spend, currency)}</p></Panel>
          <Panel title="Forecast vs budget">
            <p className="text-2xl font-semibold">{forecast == null ? "—" : money(forecast, currency)}</p>
            <p className="text-xs text-[#717171]">{delta == null ? "Set a project budget to compare" : delta > 0 ? `Over budget by ${money(delta, currency)}` : `Under budget by ${money(Math.abs(delta), currency)}`}</p>
          </Panel>
        </div>
      ) : (
        <Panel title="Cost is hidden"><p className="text-sm text-[#717171]">Your role can see resources in this project, not billing.</p></Panel>
      )}
      {view.canSeeCost ? (
        <div className="grid gap-3 lg:grid-cols-3">
          <Panel title={view.trend?.title || "Spend"}>
            {view.trend?.points?.length ? <SpendArea data={view.trend.points} /> : <p className="text-sm text-[#717171]">No cost rows for this period.</p>}
          </Panel>
          <Panel title={`Spend split · ${view.range?.label || ""}`}>
            {view.services?.length ? (<><SplitDonut data={view.services} /><DonutLegend data={view.services} /></>) : <p className="text-sm text-[#717171]">No service costs for this period.</p>}
          </Panel>
        </div>
      ) : null}
      {view.canSeeCost ? (
        <Panel title={`Databricks usage · ${view.range?.label || ""}`}>
          {view.databricks?.series?.length ? <UsageLines data={view.databricks.points} series={view.databricks.series} /> : <p className="text-sm text-[#717171]">No Azure Databricks usage quantity in this period.</p>}
          <Link href="/databricks" className="text-xs font-semibold text-[#E2773C]">Open workspaces</Link>
        </Panel>
      ) : null}
      <Panel title="Recent activity">
        {(view.activity || []).length === 0 ? <p className="text-sm text-[#717171]">No activity log events in the last 7 days.</p> : null}
        <ul className="space-y-2">
          {(view.activity || []).map((item) => (
            <li key={item.id}><p className="text-sm">{item.text}</p></li>
          ))}
        </ul>
      </Panel>
      <Panel title="In this project">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Link href="/vms" className="rounded-xl border border-[#e7e5e4] p-3">Virtual machines</Link>
          <Link href="/databricks" className="rounded-xl border border-[#e7e5e4] p-3">Databricks</Link>
          <Link href="/pipelines" className="rounded-xl border border-[#e7e5e4] p-3">Data factories</Link>
          <Link href="/containers" className="rounded-xl border border-[#e7e5e4] p-3">App hosting</Link>
        </div>
      </Panel>
      {view.advisor?.[0] ? (
        <Panel title="Highest impact recommendation">
          <p className="text-sm font-semibold">{view.advisor[0].problem}</p>
          <Link href="/insights" className="text-xs font-semibold text-[#E2773C]">All advisor items</Link>
        </Panel>
      ) : null}
    </div>
  );
}

function TablePage({ title, description, rows }: { title: string; description: string; rows: Array<Record<string, string | boolean>> }) {
  const { model } = useConsole();
  const view = readyModel(model);
  if (!view) return null;
  return (
    <div className="space-y-4">
      <PageHead eyebrow={view.project?.name} title={title} description={description} />
      <Panel>
        {rows.length === 0 ? <p className="text-sm text-[#717171]">Nothing in this project for that view.</p> : null}
        <table className="w-full text-left text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id || row.name)} className="border-t border-[#e7e5e4]">
                <td className="py-2 font-semibold">{String(row.name || "")}</td>
                <td className="py-2 text-[#717171]">{String(row.group || row.kind || row.state || row.location || "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

export function VmsPage() {
  const { model } = useConsole();
  return <TablePage title="Virtual machines" description="Power state from Azure CLI for subscriptions on this project." rows={model?.vms || []} />;
}

export function HostingPage() {
  const { model } = useConsole();
  return <TablePage title="App hosting" description="Container Apps, AKS, and App Service in the attached subscriptions." rows={model?.hosting || []} />;
}

export function DatabricksPage() {
  const { model } = useConsole();
  const view = readyModel(model);
  if (!view) return null;
  return (
    <div className="space-y-4">
      <PageHead eyebrow={view.project?.name} title="Databricks" description="Workspaces from Azure, and usage quantity from Cost Management when this role can see billing." />
      {view.canSeeCost && view.databricks?.series?.length ? <Panel title="Usage"><UsageLines data={view.databricks.points} series={view.databricks.series} /></Panel> : null}
      <TablePage title="Workspaces" description="Azure Databricks workspaces on this project." rows={view.workspaces || []} />
    </div>
  );
}

export function LakesPage() {
  const { model } = useConsole();
  const rows = (model?.storage || []).map((item) => ({
    ...item,
    name: String(item.name || ""),
    kind: item.hierarchical ? "HNS" : "Blob",
  }));
  return <TablePage title="Storage" description="Storage accounts in this project. Hierarchical namespace marks a data lake account." rows={rows} />;
}

export function PipelinesPage() {
  const { model } = useConsole();
  return <TablePage title="Data factories" description="Azure Data Factory accounts in the attached subscriptions." rows={model?.pipelines || []} />;
}

function ResourcesBody() {
  const params = useSearchParams();
  const kind = params.get("kind");
  const { model } = useConsole();
  const rows = (model?.resources || []).filter((item) => (kind ? item.kind === kind : true));
  return <TablePage title="Resources" description="Inventory from the subscriptions attached to this project. Other projects in the organization are not included." rows={rows} />;
}

export function ResourcesPage() {
  return (
    <Suspense fallback={<p className="text-sm text-[#717171]">Loading resources…</p>}>
      <ResourcesBody />
    </Suspense>
  );
}

export function CostsPage() {
  const { model } = useConsole();
  const view = readyModel(model);
  if (!view) return null;
  if (!view.canSeeCost) {
    return <PageHead title="Costs" description="Your role does not include billing for this project." />;
  }
  const currency = view.kpis?.currency || "USD";
  return (
    <div className="space-y-4">
      <PageHead
        eyebrow={view.project?.name}
        title="Costs"
        description={`${view.range?.spendLabel || "Spend"} is ${money(view.kpis?.spend, currency)}. Invoice PDFs need Billing Reader on the billing account and are not downloaded in this draft.`}
      />
      <Panel title={view.trend?.title}>{view.trend?.points?.length ? <SpendArea data={view.trend.points} /> : <p className="text-sm text-[#717171]">No cost rows.</p>}</Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="By service"><CostBars data={view.services || []} /></Panel>
        <Panel title="By resource group"><CostBars data={view.groups || []} /></Panel>
      </div>
    </div>
  );
}

export function AlertsPage() {
  const { model } = useConsole();
  return <TablePage title="Alerts" description="Metric alert rules from Azure Monitor." rows={(model?.alerts || []).map((item) => ({ ...item, kind: item.state }))} />;
}

export function AdvisorPage() {
  const { model } = useConsole();
  const rows = (model?.advisor || []).map((item) => ({ id: item.id, name: item.problem, kind: item.impact || item.category }));
  return <TablePage title="Advisor" description="Azure Advisor recommendations for the attached subscriptions. These are not generated locally." rows={rows} />;
}

function ExecutorPanel({ orgId }: { orgId: string }) {
  const [mode, setMode] = useState("on_demand");
  const [windowHours, setWindowHours] = useState("12");
  const [state, setState] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!orgId) return;
    void fetch(`/api/orgs/${orgId}/executor-settings`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) return;
        const body = (await response.json()) as { mode?: string; window_hours?: number; actual_state?: string };
        if (body.mode) setMode(body.mode);
        if (body.window_hours) setWindowHours(String(body.window_hours));
        if (body.actual_state) setState(body.actual_state);
      })
      .catch(() => undefined);
  }, [orgId]);

  if (!orgId) return null;
  return (
    <Panel title="Executor pool">
      <p className="mb-3 text-sm text-[#717171]">On demand, a timed window, or a schedule. Window length is 6, 12, or 24 hours.</p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (event) => {
          event.preventDefault();
          const response = await fetch(`/api/orgs/${orgId}/executor-settings`, {
            method: "PUT",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode, window_hours: Number(windowHours) }),
          });
          setNote(response.ok ? "Executor settings saved." : "Could not save executor settings.");
        }}
      >
        <label className="text-sm">Mode
          <select className="mt-1 block h-11 rounded-2xl border border-[#e7e5e4] px-3" value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="on_demand">On demand</option>
            <option value="window">Window</option>
            <option value="schedule">Schedule</option>
          </select>
        </label>
        <label className="text-sm">Window hours
          <select className="mt-1 block h-11 rounded-2xl border border-[#e7e5e4] px-3" value={windowHours} onChange={(event) => setWindowHours(event.target.value)}>
            <option value="6">6</option>
            <option value="12">12</option>
            <option value="24">24</option>
          </select>
        </label>
        <button type="submit" className="h-11 rounded-2xl bg-[#E2773C] px-4 text-sm font-semibold text-white">Save pool</button>
      </form>
      {state ? <p className="mt-2 text-xs text-[#717171]">State {state}</p> : null}
      {note ? <p className="mt-2 text-sm">{note}</p> : null}
    </Panel>
  );
}

export function OrganizationPage() {
  const { model, refresh } = useConsole();
  const data = model?.workspace;
  const [secret, setSecret] = useState("");
  const [saved, setSaved] = useState("");
  if (!data) return <p className="text-sm text-[#717171]">Loading organization…</p>;
  return (
    <div className="space-y-4">
      <PageHead eyebrow={data.org?.name} title="Organization" description={`${data.orgRole || "Member"}. Projects and Azure subscriptions in this organization are not visible to any other client.`} />
      {!data.canManage ? (
        <Panel title="Your access">
          <ul className="space-y-2 text-sm">
            {(data.projects || []).map((item) => (
              <li key={item.id}>{item.name} · {item.role}</li>
            ))}
            {(data.projects || []).length === 0 ? <li>You are not on a project yet.</li> : null}
          </ul>
        </Panel>
      ) : (
        <>
          <Panel title="Azure app registration">
            <p className="mb-3 text-sm text-[#717171]">Grant the app Reader and Cost Management Reader. Do not grant Owner. The default connection name is Production reader.</p>
            <form
              className="grid gap-3 md:grid-cols-2"
              onSubmit={async (event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                const response = await fetch("/api/connections", {
                  method: "POST",
                  credentials: "include",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    name: String(form.get("name") || "Production reader"),
                    tenantId: String(form.get("tenantId") || ""),
                    clientId: String(form.get("clientId") || ""),
                    clientSecret: secret,
                  }),
                });
                setSecret("");
                setSaved(response.ok ? "Saved. The secret field was cleared." : "That did not save.");
                refresh();
              }}
            >
              <label className="text-sm">Name<input name="name" defaultValue="Production reader" className="mt-1 h-11 w-full rounded-2xl border border-[#e7e5e4] px-3" /></label>
              <label className="text-sm">Tenant ID<input name="tenantId" className="mt-1 h-11 w-full rounded-2xl border border-[#e7e5e4] px-3" /></label>
              <label className="text-sm">Client ID<input name="clientId" className="mt-1 h-11 w-full rounded-2xl border border-[#e7e5e4] px-3" /></label>
              <label className="text-sm">Client secret<input name="clientSecret" type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="new-password" className="mt-1 h-11 w-full rounded-2xl border border-[#e7e5e4] px-3" /></label>
              <button type="submit" className="h-11 rounded-2xl bg-[#E2773C] px-4 text-sm font-semibold text-white">Test and save</button>
            </form>
            {saved ? <p className="mt-2 text-sm">{saved}</p> : null}
            <ul className="mt-3 space-y-2 text-sm">
              {(data.connections || []).map((item) => (
                <li key={item.id}>{item.name} · {item.status} · {item.clientHint}</li>
              ))}
            </ul>
          </Panel>
          <Panel title="Project">
            <p className="text-sm text-[#717171]">Map connections onto a project. A connection is not stored twice on one project.</p>
          </Panel>
          <Panel title="Members">
            <ul className="space-y-2 text-sm">
              {(data.members || []).map((item) => (
                <li key={item.id}>{item.name} · {item.role}</li>
              ))}
            </ul>
          </Panel>
          <ExecutorPanel orgId={data.org?.id || ""} />
        </>
      )}
    </div>
  );
}
