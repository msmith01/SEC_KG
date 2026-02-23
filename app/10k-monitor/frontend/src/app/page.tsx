/**
 * Dashboard — company watchlist with search.
 * Pure server component; search uses HTML form → URL query param.
 */
import { getCompanies, type Company } from "@/lib/api";

interface PageProps {
  searchParams: { q?: string };
}

function SeverityDot({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span className="inline-block w-2 h-2 rounded-full bg-indigo-400 ml-1" />
  );
}

function CompanyCard({ company }: { company: Company }) {
  const filingCount = company.filing_count ?? 0;
  const latestYear = company.latest_date
    ? new Date(company.latest_date).getFullYear()
    : null;

  return (
    <a
      href={`/company/${company.cik}`}
      className="
        block bg-white rounded-xl border border-slate-200 p-5
        hover:border-indigo-300 hover:shadow-md transition-all duration-150
        group
      "
    >
      {/* Ticker */}
      <div className="flex items-start justify-between mb-2">
        <span className="font-mono font-bold text-xl text-indigo-600 group-hover:text-indigo-700">
          {company.ticker || "—"}
        </span>
        {filingCount > 0 && (
          <span className="text-xs text-slate-400 bg-slate-50 px-2 py-0.5 rounded-full border border-slate-200">
            {filingCount} filing{filingCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Company name */}
      <p className="text-sm text-slate-700 font-medium leading-tight mb-3 line-clamp-2">
        {company.name}
      </p>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>CIK {company.cik}</span>
        {latestYear && (
          <span className="text-slate-500">Latest {latestYear}</span>
        )}
      </div>

      <div className="mt-3 text-xs text-indigo-500 font-medium group-hover:text-indigo-600 flex items-center gap-1">
        View filings
        <span className="group-hover:translate-x-0.5 transition-transform inline-block">→</span>
      </div>
    </a>
  );
}

export default async function Dashboard({ searchParams }: PageProps) {
  const q = searchParams.q?.trim() ?? "";
  let companies: Company[] = [];
  let error: string | null = null;

  try {
    companies = await getCompanies(q || undefined);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to connect to backend";
  }

  return (
    <div>
      {/* ── Header ───────────────────────────────────────────── */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-1">
          Risk Factor Delta Monitor
        </h1>
        <p className="text-slate-500 text-sm">
          Compare consecutive 10-K Risk Factor sections to spot material language changes.
        </p>
      </div>

      {/* ── Search ───────────────────────────────────────────── */}
      <form method="get" action="/" className="mb-6 flex gap-2 max-w-lg">
        <input
          type="text"
          name="q"
          defaultValue={q}
          placeholder="Search by ticker or company name…"
          className="
            flex-1 px-4 py-2.5 rounded-lg border border-slate-300
            text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400
            focus:border-transparent bg-white
          "
        />
        <button
          type="submit"
          className="
            px-5 py-2.5 bg-indigo-600 text-white text-sm font-medium
            rounded-lg hover:bg-indigo-700 transition-colors
          "
        >
          Search
        </button>
        {q && (
          <a
            href="/"
            className="
              px-4 py-2.5 border border-slate-300 text-sm text-slate-600
              rounded-lg hover:bg-slate-50 transition-colors
            "
          >
            Clear
          </a>
        )}
      </form>

      {/* ── Error state ──────────────────────────────────────── */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-sm text-red-700">
          <strong>Backend unavailable:</strong> {error}
          <br />
          <span className="text-red-500 text-xs">
            Make sure the FastAPI server is running on port 8000.
          </span>
        </div>
      )}

      {/* ── Results meta ─────────────────────────────────────── */}
      {!error && (
        <p className="text-xs text-slate-400 mb-4">
          {q
            ? `${companies.length} result${companies.length !== 1 ? "s" : ""} for "${q}"`
            : `Showing ${companies.length} companies (use search to filter)`}
        </p>
      )}

      {/* ── Company grid ─────────────────────────────────────── */}
      {companies.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {companies.map((c) => (
            <CompanyCard key={c.cik} company={c} />
          ))}
        </div>
      ) : (
        !error && (
          <div className="text-center py-20 text-slate-400">
            <p className="text-4xl mb-3">🔍</p>
            <p className="text-sm">
              {q
                ? `No companies found for "${q}"`
                : "No companies indexed yet. Check the backend logs."}
            </p>
          </div>
        )
      )}
    </div>
  );
}
