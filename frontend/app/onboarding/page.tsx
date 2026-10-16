import { OnboardingPage } from "../../components/onboarding-page";
import { LiveFrame } from "../../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <OnboardingPage />
    </LiveFrame>
  );
}
