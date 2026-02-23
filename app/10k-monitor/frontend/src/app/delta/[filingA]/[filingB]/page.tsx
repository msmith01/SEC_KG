/**
 * Delta page — side-by-side risk factor diff between two filings.
 * Pure server component; all diff data computed by the FastAPI backend.
 */
import { getDelta, type DiffBlock, type Severity, type TopChange } from "@/lib/api";

interface PageProps {
  params: { filingA: string; filingB: string };
}

// ── Severity badge ─────────────────────────────────────────────────────────

function SeverityBadge({ level }: { level: Severity }) {
  const styles: Record<Severity, string> = {
    HIGH: "bg-red-100 text-red-800 border-red-300",
    MED:  "bg-amber-100 text-amber-800 border-amber-300",
    LOW:  "bg-slate-100 text-slate-600 border-slate-300",
    NONE: "bg-slate-100 text-slate-400 border-slate-200",
  };
  const labels: Record<Severity, string> = {
    HIGH: "HIGH",
    MED:  "MED",
    LOW:  "LOW",
    NONE: "NO CHANGE",
  };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${styles[level]}`}
    >
      {labels[level]}
    </span>
  );
}

function SeverityIcon({ level }: { level: Severity }) {
  if (level === "HIGH") return <span title="High">🔴</span>;
  if (level === "MED")  return <span title="Medium">🟡</span>;
  return                       <span title="Low">🟢</span>;
}

// ── Top changes summary ────────────────────────────────────────────────────

function TopChangeCard({ change }: { change: TopChange }) {
  const bg =
    change.severity === "HIGH"
      ? "bg-red-50 border-red-200"
      : change.severity === "MED"
      ? "bg-amber-50 border-amber-200"
      : "bg-slate-50 border-slate-200";

  return (
    <div className={`rounded-lg border p-4 ${bg}`}>
      <div className="flex items-start gap-2 mb-2">
        <SeverityIcon level={change.severity} />
        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            {change.type === "added" ? "Added" : "Removed"} ·{" "}
          </span>
          <span className="text-sm font-medium text-slate-800">{change.why}</span>
        </div>
      </div>
      <p className="text-xs text-slate-600 line-clamp-3 leading-relaxed pl-6">
        &ldquo;{change.text}&rdquo;
      </p>
    </div>
  );
}

// ── Diff renderer ──────────────────────────────────────────────────────────

function DiffLine({ block }: { block: DiffBlock }) {
  if (block.type === "collapsed") {
    return (
      <div className="py-2 px-4 text-xs text-slate-400 italic text-center select-none">
        ··· {block.count} unchanged sentence{block.count !== 1 ? "s" : ""} ···
      </div>
    );
  }

  const classes =
    block.type === "added"
      ? "diff-added text-green-900"
      : block.type === "removed"
      ? "diff-removed text-red-900"
      : "diff-context text-slate-600";

  const prefix =
    block.type === "added"
      ? "+"
      : block.type === "removed"
      ? "−"
      : " ";

  const hasSeverity =
    block.severity && block.severity !== "LOW" && block.type !== "context";

  return (
    <div
      className={`flex gap-3 px-4 py-1.5 text-sm leading-relaxed ${classes}`}
    >
      <span className="font-mono text-xs w-4 flex-shrink-0 opacity-50 mt-0.5 select-none">
        {prefix}
      </span>
      <span className="flex-1">{block.text}</span>
      {hasSeverity && (
        <span className="flex-shrink-0 self-start mt-0.5">
          <SeverityBadge level={block.severity!} />
        </span>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

function formatDate(dateStr: string) {
  const d = new Date(dateStr + "T12:00:00Z");
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export default async function DeltaPage({ params }: PageProps) {
  const accLatest   = decodeURIComponent(params.filingA);
  const accPrevious = decodeURIComponent(params.filingB);

  let delta;
  let error: string | null = null;

  try {
    delta = await getDelta(accLatest, accPrevious);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to compute delta";
  }

  if (error || !delta) {
    return (
      <div>
        <a href="/" className="text-sm text-slate-500 hover:text-indigo-600 mb-6 inline-block">
          ← Dashboard
        </a>
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
          <strong>Error:</strong> {error}
        </div>
      </div>
    );
  }

  const { company, latest_filing, previous_filing, stats, top_changes, diff_blocks, severity_score } = delta;

  return (
    <div>
      {/* ── Breadcrumb ─────────────────────────────────────────── */}
      <a
        href={`/company/${company.cik}`}
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-indigo-600 transition-colors mb-6"
      >
        ← {company.ticker}
      </a>

      {/* ── Page header ────────────────────────────────────────── */}
      <div className="flex items-start justify-between flex-wrap gap-4 mb-6">
        <div>
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="font-mono font-bold text-2xl text-indigo-600">
              {company.ticker}
            </span>
            <h1 className="text-xl font-semibold text-slate-900">
              Risk Factors — Delta
            </h1>
          </div>
          <p className="text-slate-500 text-sm mt-1">
            <span className="font-medium text-slate-700">
              FY {latest_filing.fiscal_year ?? "—"}
            </span>{" "}
            ({formatDate(latest_filing.filing_date)}){" "}
            <span className="text-slate-400 mx-1">vs</span>
            <span className="font-medium text-slate-700">
              FY {previous_filing.fiscal_year ?? "—"}
            </span>{" "}
            ({formatDate(previous_filing.filing_date)})
          </p>
        </div>
        <SeverityBadge level={severity_score} />
      </div>

      {/* ── Stats bar ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        {[
          { label: "Added",     value: stats.added_sentences,     color: "text-green-700 bg-green-50 border-green-200" },
          { label: "Removed",   value: stats.removed_sentences,   color: "text-red-700 bg-red-50 border-red-200" },
          { label: "Unchanged", value: stats.unchanged_sentences, color: "text-slate-600 bg-slate-50 border-slate-200" },
          { label: "Total Δ",   value: stats.total_changes,       color: "text-indigo-700 bg-indigo-50 border-indigo-200" },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            className={`rounded-lg border px-4 py-3 text-center ${color}`}
          >
            <div className="text-2xl font-bold">{value}</div>
            <div className="text-xs font-medium mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* ── Top changes ────────────────────────────────────────── */}
      {top_changes.length > 0 && (
        <section className="mb-8">
          <h2 className="text-base font-semibold text-slate-700 mb-3">
            Notable Changes
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {top_changes.map((c, i) => (
              <TopChangeCard key={i} change={c} />
            ))}
          </div>
        </section>
      )}

      {/* ── Full diff ──────────────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-slate-700 mb-3">
          Full Diff
        </h2>
        <div className="text-xs text-slate-400 mb-3 flex gap-4">
          <span>
            <span className="inline-block w-3 h-3 rounded-sm bg-green-200 mr-1 align-middle" />
            Added
          </span>
          <span>
            <span className="inline-block w-3 h-3 rounded-sm bg-red-200 mr-1 align-middle" />
            Removed
          </span>
          <span>
            <span className="inline-block w-3 h-3 rounded-sm bg-slate-100 mr-1 align-middle border" />
            Unchanged
          </span>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden divide-y divide-slate-100">
          {diff_blocks.length === 0 ? (
            <div className="p-8 text-center text-slate-400 text-sm">
              No differences found — sections appear identical.
            </div>
          ) : (
            diff_blocks.map((block, i) => (
              <DiffLine key={i} block={block} />
            ))
          )}
        </div>
      </section>

      {/* ── Accession numbers (debug/reference) ────────────────── */}
      <details className="mt-6 text-xs text-slate-400">
        <summary className="cursor-pointer hover:text-slate-600">
          Accession details
        </summary>
        <div className="mt-2 font-mono bg-slate-50 rounded p-3 space-y-1">
          <div>Latest:   {accLatest}</div>
          <div>Previous: {accPrevious}</div>
        </div>
      </details>
    </div>
  );
}
