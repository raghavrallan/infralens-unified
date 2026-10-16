import { LiveFrame } from "../../components/live/console";
import { EstateOverview } from "../../components/live/pages";

export default function Page() {
  return (
    <LiveFrame>
      <h1 className="sr-only">Estate overview</h1>
      <EstateOverview />
    </LiveFrame>
  );
}
