import { DashboardFindingsPage } from "../../../components/dashboard-findings-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardFindingsPage embedded />
    </LiveFrame>
  );
}
