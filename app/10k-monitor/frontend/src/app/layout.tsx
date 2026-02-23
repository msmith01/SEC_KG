import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "10K Monitor",
  description: "SEC 10-K Risk Factor Delta Analysis",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        {/* ── Top Nav ──────────────────────────────────────── */}
        <header className="bg-slate-900 text-white shadow-lg">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-4">
            <a href="/" className="flex items-center gap-2 group">
              <span className="text-indigo-400 text-xl font-bold group-hover:text-indigo-300 transition-colors">
                ◈
              </span>
              <span className="font-semibold text-lg tracking-tight">
                10K Monitor
              </span>
            </a>
            <span className="text-slate-500 text-sm hidden sm:block">
              SEC Risk Factor Delta Analysis
            </span>
          </div>
        </header>

        {/* ── Page content ─────────────────────────────────── */}
        <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
