import { DashboardArchitecturePage } from "../../../components/dashboard-architecture-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardArchitecturePage embedded />
    </LiveFrame>
  );
}
