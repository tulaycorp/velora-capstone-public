import { FullScreenLoading } from "@/components/app/full-screen-loading";

export default function PostAuthHandoffLoading() {
  return (
    <FullScreenLoading
      label="Opening Velora"
      message="Checking your workspace access."
    />
  );
}
