"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CostSlice, EstatePoint, UsageSeries } from "./types";

const PALETTE = ["#E2773C", "#C45E28", "#F2A365", "#0084FF", "#0BAA60"];

const tip = { border: "none", borderRadius: 12, fontSize: 12 };

export function SpendArea({ data }: { data: EstatePoint[] }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <CartesianGrid stroke="#e7e5e4" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={tip} />
          <Area dataKey="spend" stroke="#E2773C" fill="#F2A365" fillOpacity={0.35} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CostBars({ data }: { data: CostSlice[] }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 24 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={tip} />
          <Bar dataKey="cost" radius={6}>
            {data.map((item) => (
              <Cell key={item.name} fill={item.color || PALETTE[0]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SplitDonut({ data }: { data: CostSlice[] }) {
  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="cost" nameKey="name" innerRadius={48} outerRadius={70}>
            {data.map((item, index) => (
              <Cell key={item.name} fill={item.color || PALETTE[index % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={tip} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DonutLegend({ data }: { data: CostSlice[] }) {
  return (
    <ul className="mt-2 space-y-1 text-xs">
      {data.map((item) => (
        <li key={item.name} className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
            {item.name}
          </span>
          <span className="tabular-nums">{item.cost}</span>
        </li>
      ))}
    </ul>
  );
}

export function UsageLines({
  data,
  series,
}: {
  data: Array<Record<string, string | number>>;
  series: UsageSeries[];
}) {
  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <CartesianGrid stroke="#e7e5e4" vertical={false} />
          <XAxis dataKey="day" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={tip} />
          {series.map((item) => (
            <Area key={item.key} dataKey={item.key} name={item.name} stroke={item.color} fill={item.color} fillOpacity={0.15} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LineBars({ data }: { data: CostSlice[] }) {
  return <CostBars data={data} />;
}
