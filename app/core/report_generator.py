"""
Evidence Report Generator.

Transforms a PersonProfile into exportable evidence formats:
- Full structured JSON with SHA-256 cryptographic provenance hash
- Clean CSV spreadsheet export
- Executive printable HTML / PDF dossier
"""

import csv
import hashlib
import html
import io
import json
import uuid
from datetime import datetime, timezone

from app.schemas.person import PersonProfile
from app.schemas.report import EvidenceReport


def compute_integrity_hash(person_id: uuid.UUID, canonical_name: str, claims_data: list) -> str:
    """
    Computes a deterministic SHA-256 checksum over the person ID, name,
    and sorted claims with evidence spans.
    """
    canonical_representation = {
        "person_id": str(person_id),
        "canonical_name": canonical_name,
        "claims": sorted(
            [
                {
                    "type": str(c.get("type")),
                    "value": str(c.get("value")),
                    "sources": sorted([str(e.get("source_url", "")) for e in c.get("evidence", [])]),
                }
                for c in claims_data
            ],
            key=lambda x: (x["type"], x["value"]),
        ),
    }
    raw_bytes = json.dumps(canonical_representation, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def build_evidence_report(profile: PersonProfile) -> EvidenceReport:
    """
    Builds an EvidenceReport model from a PersonProfile.
    """
    claims_dict_list = [c.model_dump() for c in profile.claims]

    unique_sources = set()
    for claim in profile.claims:
        for ev in claim.evidence:
            if ev.source_url:
                unique_sources.add(ev.source_url)

    integrity_hash = compute_integrity_hash(
        person_id=profile.person_id,
        canonical_name=profile.canonical_name,
        claims_data=claims_dict_list,
    )

    return EvidenceReport(
        report_id=uuid.uuid4(),
        generated_at=datetime.now(timezone.utc),
        person_id=profile.person_id,
        canonical_name=profile.canonical_name,
        status=profile.status,
        summary=profile.summary,
        claims_count=len(profile.claims),
        unique_sources_count=len(unique_sources),
        claims=profile.claims,
        conflict_flags=profile.conflict_flags,
        staleness_flags=profile.staleness_flags,
        sha256_integrity_hash=integrity_hash,
    )


def export_report_csv(report: EvidenceReport) -> str:
    """
    Serializes an EvidenceReport into a CSV table of claims and evidence items.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "Person ID",
        "Canonical Name",
        "Claim ID",
        "Claim Type",
        "Claim Value",
        "Confidence",
        "Is Stale",
        "Staleness Reason",
        "Source Type",
        "Source URL",
        "Evidence Excerpt",
        "Retrieved At",
    ])

    for claim in report.claims:
        if not claim.evidence:
            writer.writerow([
                str(report.person_id),
                report.canonical_name,
                str(claim.claim_id),
                claim.type,
                claim.value,
                f"{claim.confidence:.2f}",
                "Yes" if claim.is_stale else "No",
                claim.staleness_reason or "",
                "",
                "",
                "",
                "",
            ])
        else:
            for ev in claim.evidence:
                writer.writerow([
                    str(report.person_id),
                    report.canonical_name,
                    str(claim.claim_id),
                    claim.type,
                    claim.value,
                    f"{claim.confidence:.2f}",
                    "Yes" if claim.is_stale else "No",
                    claim.staleness_reason or "",
                    ev.source_type,
                    ev.source_url,
                    ev.excerpt,
                    ev.retrieved_at.isoformat() if ev.retrieved_at else "",
                ])

    return output.getvalue()


def export_report_html(report: EvidenceReport) -> str:
    """
    Generates a standalone, beautifully styled printable HTML evidence dossier.
    """
    name = html.escape(report.canonical_name)
    person_id = str(report.person_id)
    report_id = str(report.report_id)
    generated_at = report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    sha_hash = report.sha256_integrity_hash

    # Build summary section
    summary_html = ""
    if report.summary and report.summary.sentences:
        sentences_markup = []
        for s in report.summary.sentences:
            cite_badges = "".join([f'<sup class="cite-ref">[{str(cid)[:4]}]</sup>' for cid in s.claim_ids])
            sentences_markup.append(f"<span>{html.escape(s.text)}{cite_badges} </span>")
        summary_html = f"""
        <div class="report-section summary-box">
            <h2 class="section-title">Cited Profile Summary</h2>
            <div class="summary-body">
                {''.join(sentences_markup)}
            </div>
            <div class="summary-footnote">Each sentence is strictly derived from and cited against verified source claims.</div>
        </div>
        """

    # Build conflict flags
    conflicts_html = ""
    if report.conflict_flags or report.staleness_flags:
        flags_items = []
        for cf in report.conflict_flags:
            flags_items.append(f"""
            <div class="flag-card flag-conflict">
                <div class="flag-header">
                    <span class="flag-tag conflict-tag">CONFLICT: {html.escape(cf.conflict_type)}</span>
                    <span class="flag-sev">{html.escape(cf.severity.upper())} SEVERITY</span>
                </div>
                <div class="flag-desc">{html.escape(cf.description)}</div>
                <div class="flag-prompt"><strong>Action:</strong> {html.escape(cf.action_prompt)}</div>
            </div>
            """)
        for sf in report.staleness_flags:
            flags_items.append(f"""
            <div class="flag-card flag-stale">
                <div class="flag-header">
                    <span class="flag-tag stale-tag">STALENESS NOTICE</span>
                    <span class="flag-sev">{sf.days_old or '?'} DAYS OLD</span>
                </div>
                <div class="flag-desc">{html.escape(sf.reason)}</div>
            </div>
            """)
        conflicts_html = f"""
        <div class="report-section">
            <h2 class="section-title">Audit, Discrepancy & Staleness Flags</h2>
            <div class="flags-grid">
                {''.join(flags_items)}
            </div>
        </div>
        """

    # Build claims table
    claims_rows = []
    for claim in report.claims:
        stale_badge = '<span class="badge-stale">Stale</span>' if claim.is_stale else ""
        for i, ev in enumerate(claim.evidence or [{}]):
            source_link = (
                f'<a href="{html.escape(ev.source_url)}" target="_blank" rel="noopener">{html.escape(ev.source_url[:45])}…</a>'
                if getattr(ev, "source_url", None)
                else "—"
            )
            excerpt = html.escape(getattr(ev, "excerpt", "") or "—")
            retrieved = getattr(ev, "retrieved_at", None)
            retrieved_str = retrieved.strftime("%Y-%m-%d") if retrieved else "—"
            source_type = html.escape(getattr(ev, "source_type", "unknown"))

            claims_rows.append(f"""
            <tr>
                <td><strong>{html.escape(claim.type)}</strong></td>
                <td>
                    <div class="claim-val">{html.escape(claim.value)} {stale_badge}</div>
                    <div class="claim-id-sub">Claim #{str(claim.claim_id)[:8]}</div>
                </td>
                <td style="text-align: center;">{int(claim.confidence * 100)}%</td>
                <td><span class="type-pill">{source_type}</span></td>
                <td>{source_link}</td>
                <td class="excerpt-cell">{excerpt}</td>
                <td style="font-size: 11px;">{retrieved_str}</td>
            </tr>
            """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Evidence Report — {name} — PersonSearch</title>
<style>
    :root {{
        --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        --color-bg: #ffffff;
        --color-text: #1e293b;
        --color-text-dim: #64748b;
        --color-border: #e2e8f0;
        --color-accent: #2563eb;
        --color-warning: #d97706;
        --color-danger: #dc2626;
        --color-bg-subtle: #f8fafc;
    }}
    @page {{
        size: A4;
        margin: 18mm 14mm;
    }}
    body {{
        margin: 0;
        padding: 24px;
        font-family: var(--font);
        color: var(--color-text);
        background: var(--color-bg);
        font-size: 13px;
        line-height: 1.5;
    }}
    .report-wrap {{
        max-width: 1000px;
        margin: 0 auto;
    }}
    .report-header {{
        border-bottom: 2px solid var(--color-accent);
        padding-bottom: 16px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }}
    .brand-title {{
        font-size: 20px;
        font-weight: 700;
        color: var(--color-accent);
        letter-spacing: -0.02em;
    }}
    .report-badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        background: #eff6ff;
        color: var(--color-accent);
        margin-top: 4px;
    }}
    .meta-col {{
        text-align: right;
        font-size: 12px;
        color: var(--color-text-dim);
    }}
    .disclaimer-banner {{
        background: #fefce8;
        border: 1px solid #fef08a;
        color: #854d0e;
        padding: 12px 14px;
        border-radius: 6px;
        font-size: 12px;
        margin-bottom: 20px;
    }}
    .disclaimer-banner strong {{
        color: #713f12;
    }}
    .subject-card {{
        background: var(--color-bg-subtle);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 24px;
        display: grid;
        grid-template-columns: 2fr 1fr 1fr;
        gap: 16px;
    }}
    .subject-name {{
        font-size: 22px;
        font-weight: 700;
        color: #0f172a;
    }}
    .stat-label {{
        font-size: 11px;
        text-transform: uppercase;
        color: var(--color-text-dim);
        font-weight: 600;
    }}
    .stat-val {{
        font-size: 18px;
        font-weight: 600;
        color: var(--color-text);
    }}
    .report-section {{
        margin-bottom: 24px;
    }}
    .section-title {{
        font-size: 14px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--color-text-dim);
        border-bottom: 1px solid var(--color-border);
        padding-bottom: 6px;
        margin-bottom: 12px;
    }}
    .summary-box {{
        background: #f8fafc;
        border-left: 3px solid var(--color-accent);
        padding: 14px 18px;
        border-radius: 4px;
    }}
    .summary-body {{
        font-size: 14px;
        line-height: 1.6;
    }}
    .cite-ref {{
        color: var(--color-accent);
        font-weight: 600;
        font-size: 10px;
        padding: 0 2px;
    }}
    .summary-footnote {{
        font-size: 11px;
        color: var(--color-text-dim);
        margin-top: 8px;
        font-style: italic;
    }}
    .flags-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 12px;
    }}
    .flag-card {{
        border: 1px solid var(--color-border);
        border-radius: 6px;
        padding: 12px;
        background: #fff;
    }}
    .flag-conflict {{
        border-left: 3px solid var(--color-warning);
    }}
    .flag-stale {{
        border-left: 3px solid #64748b;
    }}
    .flag-header {{
        display: flex;
        justify-content: space-between;
        margin-bottom: 6px;
        font-size: 11px;
        font-weight: 600;
    }}
    .conflict-tag {{ color: var(--color-warning); }}
    .stale-tag {{ color: #64748b; }}
    .flag-desc {{ font-size: 12px; margin-bottom: 4px; }}
    .flag-prompt {{ font-size: 11px; color: var(--color-text-dim); }}
    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }}
    th {{
        text-align: left;
        padding: 8px 10px;
        background: #f1f5f9;
        border-bottom: 2px solid var(--color-border);
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        color: var(--color-text-dim);
    }}
    td {{
        padding: 8px 10px;
        border-bottom: 1px solid var(--color-border);
        vertical-align: top;
    }}
    tr:nth-child(even) {{
        background: #fcfdfe;
    }}
    .claim-val {{ font-weight: 600; color: #0f172a; }}
    .claim-id-sub {{ font-size: 10px; color: var(--color-text-dim); font-family: var(--font-mono); }}
    .type-pill {{
        background: #e2e8f0;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 10px;
        text-transform: uppercase;
    }}
    .excerpt-cell {{
        font-size: 11px;
        color: #475569;
        font-style: italic;
        max-width: 280px;
    }}
    .badge-stale {{
        background: #fee2e2;
        color: var(--color-danger);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 10px;
        margin-left: 4px;
    }}
    .report-footer {{
        margin-top: 36px;
        padding-top: 14px;
        border-top: 1px solid var(--color-border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 11px;
        color: var(--color-text-dim);
    }}
    .hash-box {{
        font-family: var(--font-mono);
        font-size: 10px;
        background: #f1f5f9;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    .print-btn {{
        background: var(--color-accent);
        color: #fff;
        border: none;
        padding: 6px 14px;
        border-radius: 4px;
        cursor: pointer;
        font-weight: 600;
        font-size: 12px;
    }}
    @media print {{
        .print-btn {{ display: none; }}
        body {{ padding: 0; }}
        tr {{ page-break-inside: avoid; }}
    }}
</style>
</head>
<body>
<div class="report-wrap">
    <div class="report-header">
        <div>
            <div class="brand-title">PersonSearch Evidence Dossier</div>
            <div class="report-badge">Official Due-Diligence Evidence Export</div>
        </div>
        <div class="meta-col">
            <div><strong>Report ID:</strong> {report_id}</div>
            <div><strong>Generated:</strong> {generated_at}</div>
            <div style="margin-top: 6px;">
                <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
            </div>
        </div>
    </div>

    <div class="disclaimer-banner">
        <strong>LEGAL & PRIVACY NOTICE (POSSIBLE MATCH ONLY):</strong>
        This dossier is strictly compiled from indexed public sources and verified evidence spans. All claims are labelled "possible match" and do not represent a definitive identity. To submit a correction or suppression request, refer to the PersonSearch dispute registry.
    </div>

    <div class="subject-card">
        <div>
            <div class="stat-label">Subject Canonical Name</div>
            <div class="subject-name">{name}</div>
            <div style="font-size: 11px; color: var(--color-text-dim); font-family: var(--font-mono); margin-top: 2px;">
                Cluster ID: {person_id}
            </div>
        </div>
        <div>
            <div class="stat-label">Verified Claims</div>
            <div class="stat-val">{report.claims_count}</div>
        </div>
        <div>
            <div class="stat-label">Unique Sources</div>
            <div class="stat-val">{report.unique_sources_count}</div>
        </div>
    </div>

    {summary_html}

    {conflicts_html}

    <div class="report-section">
        <h2 class="section-title">Verified Claims & Provenance Spans</h2>
        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Claim & ID</th>
                    <th style="text-align: center;">Confidence</th>
                    <th>Source Type</th>
                    <th>Source URL</th>
                    <th>Evidence Excerpt</th>
                    <th>Retrieved</th>
                </tr>
            </thead>
            <tbody>
                {''.join(claims_rows)}
            </tbody>
        </table>
    </div>

    <div class="report-footer">
        <div>
            PersonSearch V2 · Accountable Profile Discovery
        </div>
        <div class="hash-box">
            SHA-256 Provenance Checksum: {sha_hash}
        </div>
    </div>
</div>
</body>
</html>
"""
