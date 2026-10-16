import { DashboardBreakGlassPage } from "../../../components/dashboard-break-glass-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardBreakGlassPage embedded />
    </LiveFrame>
  );
}
