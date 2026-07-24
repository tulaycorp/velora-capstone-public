import type { Metadata } from "next";
import { headers } from "next/headers";
import { ClerkAppProvider } from "@/components/auth/clerk-ui";
import { CONTENT_SECURITY_POLICY_NONCE_HEADER } from "@/lib/content-security-policy";
import { isClerkFrontendConfigured } from "@/lib/clerk-config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Velora",
  description: "Workspace for shaping artwork into ready-to-send print-on-demand products."
};

export default async function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const clerkEnabled = isClerkFrontendConfigured();
  const nonce = (await headers()).get(CONTENT_SECURITY_POLICY_NONCE_HEADER) ?? undefined;

  const content = clerkEnabled ? (
    <ClerkAppProvider nonce={nonce}>
      {children}
    </ClerkAppProvider>
  ) : (
    children
  );

  return (
    <html lang="en" className="bg-background text-foreground">
      <body className="bg-background text-foreground">{content}</body>
    </html>
  );
}
