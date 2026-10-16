import { SettingsPage } from "../../../components/settings-page";
import { LiveFrame } from "../../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <SettingsPage embedded />
    </LiveFrame>
  );
}
