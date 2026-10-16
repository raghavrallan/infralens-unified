import { ChatPage } from "../components/chat-page";
import { LiveFrame } from "../components/live/console";

export default function Page() {
  return (
    <LiveFrame>
      <ChatPage embedded />
    </LiveFrame>
  );
}
