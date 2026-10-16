import { LiveFrame } from "../../components/live/console";
import { WikiPage } from "../../components/wiki-page";

export default function Page() {
  return (
    <LiveFrame>
      <WikiPage embedded />
    </LiveFrame>
  );
}
