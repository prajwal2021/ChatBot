"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useApi } from "@/lib/api";
import { ErrorNote, Loading } from "@/components/ui";

export default function Home() {
  const router = useRouter();
  const { data, error } = useApi<{ key: string }[]>("/api/chatbots");
  useEffect(() => {
    if (data?.length) router.replace(`/${data[0].key}/servicenow`);
  }, [data, router]);
  return <div className="mx-auto max-w-md pt-32">{error ? <ErrorNote>{error}</ErrorNote> : <Loading />}</div>;
}
