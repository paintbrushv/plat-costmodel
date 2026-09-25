# plat-costmodel

Multifamily renovation cost estimation engine for Plat — a domain-expert real estate intelligence agent.

## What It Does

- **Per-unit cost estimation** with line-item breakdowns (flooring, kitchen, bath, paint, appliances, fixtures, contingency)
- **Scope of Work (SOW) generation** — contractor-ready documents from property profile
- **Contractor bid evaluation** — flags inflated line items, vague lump sums, unrealistic timelines
- **ROI gating** — 15% minimum threshold check on all renovation plans
- **Risk flagging** — age-based warnings (galvanized pipe, asbestos, foundation concerns)
- **Budget vs. actual tracking** — Yardi Voyager integration for model calibration

## Architecture

MCP tool server callable by Plat's orchestration layer. CLI-first interface.

```
Plat (agent) ──MCP──▶ plat-costmodel (tool server)
                            ├── estimate    — per-unit cost range
                            ├── sow         — scope of work generation
                            ├── evaluate    — contractor bid evaluation
                            ├── roi         — ROI threshold check
                            └── ingest      — Yardi CSV import
```

## Two Scope Levels

| Scope | Cost Range | Description |
|-------|-----------|-------------|
| Light | $3K-$5K/unit | Paint, clean, patch, hardware, carpet |
| Standard Value-Add | $12K-$18K/unit | Full kitchen/bath update, LVP, appliances, fixtures |

Gut renos excluded — don't pencil at Class C rents.

## Cost Model Inputs

- Unit square footage (<700 small, 700-950 medium, 950+ large)
- Finish tier (basic vs. upgraded)
- Number of bedrooms/bathrooms
- Property year built (drives risk flags)
- Property class (B or C)
- Market (Dallas, Birmingham — more later)

## Data Sources

- **Brain dump knowledge** — Day 1 baseline from operator experience
- **Yardi Voyager CSV exports** — historical actuals tagged to unit numbers
- **RSMeans benchmarks** — industry reference data (future)
- **Cross-user pooled data** — anonymous Glassdoor-style model (SaaS future)
