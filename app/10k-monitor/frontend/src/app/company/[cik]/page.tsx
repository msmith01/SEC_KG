/**
 * Company page — shows filing timeline and "Compare with previous" buttons.
 * Pure server component.
 */
import { getCompany, type Filing } from "@/lib/api";
import { notFound } from "next/navigation";

interface PageProps {
  params: { cik: string };
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr + "T12:00:00Z"); // avoid timezone off-by-one
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function FilingRow({
  filing,
  nextFiling,
}: {
  filing: Filing;
  nextFiling?: Filing;
}) {
  const fy = filing.fiscal_year ?? "—";
  const hasNext = !!nextFiling;

  return (
    <div className="flex items-center gap-0">
      {/* Timeline spine */}
      <div className="flex flex-col items-center mr-4 self-stretch">
        <div className="w-3 h-3 rounded-full bg-indigo-500 mt-5 z-10 flex-shrink-0" />
        {hasNext && <div className="w-0.5 bg-slate-200 flex-1 mt-1" />}
      </div>

      {/* Card */}
      <div className="flex-1 mb-4">
        <div className="bg-white rounded-xl border border-slate-200 p-5 hover:border-slate-300 transition-colors">
          <div className="flex items-center justify-between flex-wrap gap-3">
            {/* Filing info */}
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono font-bold text-indigo-600 text-sm">
                  {filing.form_type}
                </span>
                <span className="text-slate-800 font-semibold">
                  FY {fy}
                </span>
                <span className="text-slate-400 text-xs">
                  filed {formatDate(filing.filing_date)}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                {filing.accession}
              </p>
            </div>

            {/* Compare button */}
            {hasNext && nextFiling && (
              <a
                href={`/delta/${encodeURIComponent(filing.accession)}/${encodeURIComponent(nextFiling.accession)}`}
                className="
                  inline-flex items-center gap-1.5 px-4 py-2
                  bg-indigo-50 text-indigo-700 text-sm font-medium
                  rounded-lg border border-indigo-200
                  hover:bg-indigo-100 hover:border-indigo-300 transition-colors
                  whitespace-nowrap
                "
              >
                <span>Compare</span>
                <span className="font-mono text-xs">
                  FY{fy} vs FY{nextFiling.fiscal_year ?? "—"}
                </span>
                <span>→</span>
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function CompanyPage({ params }: PageProps) {
  let company;
  try {
    company = await getCompany(params.cik);
  } catch {
    notFound();
  }

  const filings: Filing[] = company.filings ?? [];

  return (
    <div>
      {/* ── Breadcrumb ────────────────────────────────────────── */}
      <a
        href="/"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-indigo-600 transition-colors mb-6"
      >
        ← Dashboard
      </a>

      {/* ── Company header ────────────────────────────────────── */}
      <div className="mb-8">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="font-mono font-bold text-3xl text-indigo-600">
            {company.ticker}
          </span>
          <h1 className="text-2xl font-semibold text-slate-900">
            {company.name}
          </h1>
        </div>
        <p className="text-slate-500 text-sm mt-1">
          CIK {company.cik} · {filings.length} filing
          {filings.length !== 1 ? "s" : ""} indexed · Risk Factors (Item 1A)
        </p>
      </div>

      {/* ── Filing timeline ───────────────────────────────────── */}
      {filings.length === 0 ? (
        <div className="text-center py-16 text-slate-400 text-sm">
          No filings indexed for this company.
        </div>
      ) : (
        <div>
          <h2 className="text-base font-semibold text-slate-700 mb-4">
            Filing Timeline
          </h2>
          <p className="text-xs text-slate-400 mb-5">
            Click Compare to see a side-by-side risk factor diff between
            consecutive annual filings.
          </p>

          <div>
            {filings.map((filing, i) => (
              <FilingRow
                key={filing.accession}
                filing={filing}
                nextFiling={filings[i + 1]}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
