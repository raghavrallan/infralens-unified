export interface EstatePoint {
  label: string;
  spend: number;
}

export interface CostSlice {
  name: string;
  cost: number;
  color: string;
}

export interface UsageSeries {
  key: string;
  name: string;
  color: string;
}

export interface EstateModel {
  status: string;
  message?: string;
  warnings?: string[];
  canSeeCost?: boolean;
  range?: { id: string; label: string; spendLabel: string };
  project?: { id?: string; name?: string; budget?: number | null } | null;
  subscriptions?: Array<{ id: string; name: string; state?: string }>;
  kpis?: {
    spend: number | null;
    currency?: string;
    forecast: number | null;
    resourceCount: number;
    vmCount: number;
    vmRunning: number;
    groupCount: number;
  };
  trend?: { title: string; points: EstatePoint[] };
  services?: CostSlice[];
  groups?: CostSlice[];
  databricks?: { series: UsageSeries[]; points: Array<Record<string, string | number>> };
  vms?: Array<Record<string, string>>;
  hosting?: Array<Record<string, string>>;
  workspaces?: Array<Record<string, string>>;
  storage?: Array<Record<string, string | boolean>>;
  pipelines?: Array<Record<string, string>>;
  resources?: Array<Record<string, string>>;
  activity?: Array<Record<string, string>>;
  alerts?: Array<Record<string, string>>;
  advisor?: Array<Record<string, string>>;
  syncedAt?: number;
  workspace?: Workspace;
}

export interface WorkspaceProject {
  id: string;
  name: string;
  budget?: number | null;
  role?: string | null;
}

export interface Workspace {
  user?: { name?: string; email?: string };
  org?: { id?: string; name?: string };
  orgs?: Array<{ id: string; name: string; role?: string }>;
  orgRole?: string;
  canManage?: boolean;
  projects?: WorkspaceProject[];
  members?: Array<{ id: string; name: string; email?: string; role: string }>;
  connections?: Array<{ id: string; name: string; status?: string; clientHint?: string }>;
}
