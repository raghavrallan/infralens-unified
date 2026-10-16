"use client";

import { useEffect } from "react";
import { BreakGlassPanel } from "./break-glass-panel";
import { DashboardShell, useDashboardContext } from "./dashboard-shell";

function BreakGlassBody() {
  const { projectId, setLoading, setUpdated } = useDashboardContext();

  useEffect(() => {
    setLoading(false);
    if (projectId) setUpdated(new Date());
  }, [projectId, setLoading, setUpdated]);

  if (!projectId) {
    return (
      <div className="empty-note">Select a project to manage break-glass access.</div>
    );
  }

  return (
    <section className="dash-col">
      <BreakGlassPanel projectId={projectId} />
    </section>
  );
}

export function DashboardBreakGlassPage({ embedded = false }: { embedded?: boolean }) {
  return (
    <DashboardShell title="Break-glass" embedded={embedded}>
      <BreakGlassBody />
    </DashboardShell>
  );
}
