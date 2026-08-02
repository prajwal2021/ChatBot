import { redirect } from "next/navigation";

export default function Home() {
  redirect("/chat/online_chat");
}
