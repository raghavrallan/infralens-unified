import { DashboardApprovalsPage } from "../../../components/dashboard-approvals-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardApprovalsPage embedded />
    </LiveFrame>
  );
}
