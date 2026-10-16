import { DashboardEngineeringPage } from "../../../components/dashboard-engineering-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <DashboardEngineeringPage embedded />
    </LiveFrame>
  );
}
