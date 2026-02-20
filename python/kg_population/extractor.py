"""
LLM-based entity and relation extraction for one filing section.

For each section type, a tailored prompt asks the LLM to return a JSON
object with two keys:
  nodes    : list of entity dicts
  relations: list of relation dicts

The extractor is stateless — it produces raw dicts that the normaliser
and writer downstream convert into typed ontology objects.
"""

from __future__ import annotations

import json
import re
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.schemas import SectionDocument, SectionType, TaggedSentence
from models.llm_client import LLMClient


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a financial knowledge graph extraction specialist working with SEC 10-K filings.
Your output must be valid JSON only — no prose, no markdown fences, no explanation.
Extract only what is explicitly stated in the text. Do not infer or hallucinate.
"""

# ── Section-specific extraction prompts ───────────────────────────────────────

_RISK_PROMPT = """\
Extract entities and relations from this Risk Factors passage from {company_name}'s 10-K filing ({fiscal_year}).

Return a JSON object with exactly two keys: "nodes" and "relations".

"nodes" is an array of objects, each with:
  type        : one of [RiskFactor, RiskDriver, RiskConsequence, Mitigation]
  title       : short label (for RiskFactor: the risk heading or a concise title)
  description : one-sentence summary (required for RiskFactor; optional for others)
  category    : risk taxonomy path, e.g. "OperationalRisk.CybersecurityRisk" (best effort)
  is_new      : true | false (only for RiskFactor — is this risk newly disclosed?)

"relations" is an array of objects, each with:
  subject_type : entity type of the source
  subject_title: title of the source entity
  relation     : one of [CAUSED_BY, MAY_RESULT_IN, MITIGATED_BY, RELATED_TO]
  object_type  : entity type of the target
  object_title : title of the target entity

Passage (filing: {accession}, sentences {start_idx}–{end_idx}):
{text}
"""

_BUSINESS_PROMPT = """\
Extract entities and relations from this Business Description passage from {company_name}'s 10-K filing ({fiscal_year}).

Return a JSON object with exactly two keys: "nodes" and "relations".

"nodes" is an array of objects, each with:
  type         : one of [BusinessSegment, Product, GeographicMarket, CustomerSegment, Competitor, Regulation]
  name         : canonical name
  description  : one-sentence description (optional)
  segment_type : for BusinessSegment: ProductSegment | ServiceSegment (optional)
  category     : for Product: HardwareProduct | SoftwareProduct | FinancialProduct (optional)
  iso_code     : for GeographicMarket: ISO 3166 country code (optional)
  revenue_pct  : for BusinessSegment: percentage of total revenue if stated (float, optional)

"relations" is an array of objects, each with:
  subject_type : always "Company"
  subject_title: company name
  relation     : one of [HAS_SEGMENT, OFFERS, OPERATES_IN, TARGETS, COMPETES_WITH, SUBJECT_TO]
  object_type  : entity type of the target
  object_title : name of the target entity

Passage (filing: {accession}, sentences {start_idx}–{end_idx}):
{text}
"""

_MDA_PROMPT = """\
Extract entities and relations from this MD&A passage from {company_name}'s 10-K filing ({fiscal_year}).

Return a JSON object with exactly two keys: "nodes" and "relations".

"nodes" is an array of objects, each with:
  type       : one of [FinancialMetric, Driver, MacroFactor, ManagementOutlook]
  name       : canonical metric/driver/factor name
  value      : numeric value if stated (float, optional)
  unit       : USD_millions | percent | units | other (optional)
  direction  : increase | decrease | flat | not_stated
  basis      : GAAP | non-GAAP (for FinancialMetric, optional)
  yoy_change : year-over-year change as float if stated (optional)
  sentiment  : positive | cautious | negative | neutral (for ManagementOutlook)
  horizon    : near_term | full_year | multi_year (for ManagementOutlook)
  driver_type: revenue_driver | cost_driver (for Driver, optional)
  text       : full quote for ManagementOutlook

"relations" is an array of objects, each with:
  subject_type : entity type of the source
  subject_title: name of the source entity
  relation     : one of [REPORTS, DRIVEN_BY, IMPACTED_BY, HAS_OUTLOOK, REFERENCES, ATTRIBUTED_TO]
  object_type  : entity type of the target
  object_title : name of the target entity

Passage (filing: {accession}, sentences {start_idx}–{end_idx}):
{text}
"""

_PROMPT_MAP = {
    SectionType.RISK_FACTORS: _RISK_PROMPT,
    SectionType.BUSINESS:     _BUSINESS_PROMPT,
    SectionType.MDA:          _MDA_PROMPT,
}

_BATCH_SIZE = 10  # sentences per LLM call


class KGExtractor:
    """
    Extracts raw entity/relation dicts from a SectionDocument via LLM.
    Output is untyped — normalisation happens downstream.
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self._client = client or LLMClient()

    def extract(
        self,
        doc: SectionDocument,
        batch_size: int = _BATCH_SIZE,
    ) -> dict:
        """
        Process all sentences in a document.

        Returns:
            {
                "nodes":     [raw entity dicts ...],
                "relations": [raw relation dicts ...],
            }
        """
        template = _PROMPT_MAP[doc.section_type]
        all_nodes: list[dict] = []
        all_relations: list[dict] = []

        sentences = doc.sentences
        for i in range(0, len(sentences), batch_size):
            batch = sentences[i : i + batch_size]
            text  = "\n".join(
                f"[{s.sentence_id}] {s.text}" for s in batch
            )
            prompt = template.format(
                company_name=doc.metadata.company_name,
                fiscal_year=doc.metadata.fiscal_year,
                accession=doc.metadata.accession_number,
                start_idx=i,
                end_idx=i + len(batch) - 1,
                text=text,
            )

            raw = self._call_llm(prompt, max_tokens=8192)
            if raw:
                all_nodes.extend(raw.get("nodes", []))
                all_relations.extend(raw.get("relations", []))

        return {"nodes": all_nodes, "relations": all_relations}

    def _call_llm(self, prompt: str, max_tokens: int = 8192) -> Optional[dict]:
        try:
            response = self._client.complete(prompt, system=_SYSTEM, max_tokens=max_tokens)
            # Strip accidental markdown fences
            response = re.sub(r"^```(?:json)?\s*", "", response.strip())
            response = re.sub(r"\s*```$", "", response.strip())
            return json.loads(response)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[KGExtractor] Parse error: {e}", file=sys.stderr)
            return None
