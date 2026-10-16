import { OrganizationsPage } from "../../components/organizations-page";
import { LiveFrame } from "../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <OrganizationsPage embedded />
    </LiveFrame>
  );
}
