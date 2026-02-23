/**
 * Typed API client — called from Next.js server components.
 * All fetches go directly to the FastAPI backend (BACKEND_URL env var).
 */

const API = process.env.BACKEND_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export interface Company {
  cik: string;
  ticker: string;
  name: string;
  filing_count: number;
  latest_date: string | null;
  earliest_date: string | null;
}

export interface Filing {
  accession: string;
  cik: string;
  ticker: string;
  company_name: string;
  form_type: string;
  filing_date: string;
  fiscal_year: number | null;
  file_path: string;
}

export interface CompanyDetail extends Company {
  filings: Filing[];
}

export type Severity = "HIGH" | "MED" | "LOW" | "NONE";

export interface DiffBlock {
  type: "added" | "removed" | "context" | "collapsed";
  text?: string;
  severity?: Severity;
  count?: number;
}

export interface TopChange {
  severity: Severity;
  type: "added" | "removed";
  text: string;
  why: string;
}

export interface Delta {
  company: { cik: string; ticker: string; name: string };
  latest_filing: Omit<Filing, "cik" | "ticker" | "company_name" | "file_path">;
  previous_filing: Omit<Filing, "cik" | "ticker" | "company_name" | "file_path">;
  section: string;
  severity_score: Severity;
  stats: {
    added_sentences: number;
    removed_sentences: number;
    unchanged_sentences: number;
    total_changes: number;
  };
  top_changes: TopChange[];
  diff_blocks: DiffBlock[];
}

// ── Fetchers ───────────────────────────────────────────────────────────────

export async function getCompanies(q?: string): Promise<Company[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  const res = await fetch(`${API}/api/companies${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch companies: ${res.status}`);
  return res.json();
}

export async function getCompany(cik: string): Promise<CompanyDetail> {
  const res = await fetch(`${API}/api/companies/${cik}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Company not found: ${cik}`);
  return res.json();
}

export async function getDelta(
  accLatest: string,
  accPrevious: string
): Promise<Delta> {
  const url = `${API}/api/delta/${encodeURIComponent(accLatest)}/${encodeURIComponent(accPrevious)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Delta computation failed: ${res.status}`);
  return res.json();
}
