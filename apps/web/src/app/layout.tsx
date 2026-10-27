import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ASI Meal Management",
  description: "Internal meal management workspace for ASI Meal.",
  applicationName: "ASI Meal Management",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
