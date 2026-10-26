import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AMD AI Factory | Mission Control",
  description: "Local-first GPU scheduling & inference observability demo",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
