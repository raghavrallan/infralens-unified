import { DashboardWorkflowsPage } from "../../../components/dashboard-workflows-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardWorkflowsPage embedded />
    </LiveFrame>
  );
}
