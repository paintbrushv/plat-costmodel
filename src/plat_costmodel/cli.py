"""CLI interface for plat-costmodel."""

import json
import sys

import click

from .bridge import prepare_renovation_program
from .estimator import estimate_unit
from .roi import check_roi
from .sow import generate_sow
from .bid_eval import evaluate_bid
from .models import ContractorBid, BidLineItem


@click.group()
def cli():
    """plat-costmodel: Multifamily renovation cost estimation engine."""
    pass


@cli.command()
@click.option("--sqft", required=True, type=float, help="Unit square footage")
@click.option("--beds", required=True, type=int, help="Number of bedrooms")
@click.option("--baths", required=True, type=int, help="Number of bathrooms")
@click.option("--scope", default="standard_value_add", type=click.Choice(["light", "standard_value_add"]))
@click.option("--finish", default="basic", type=click.Choice(["basic", "upgraded"]))
@click.option("--year-built", type=int, default=None, help="Property year built")
@click.option("--property-class", type=click.Choice(["B", "C"]), default=None)
@click.option("--market", type=str, default=None, help="Market (dallas, birmingham)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def estimate(sqft, beds, baths, scope, finish, year_built, property_class, market, json_output):
    """Estimate per-unit renovation cost with line-item breakdown."""
    est = estimate_unit(
        unit_sqft=sqft,
        bedrooms=beds,
        bathrooms=baths,
        scope_level=scope,
        finish_tier=finish,
        year_built=year_built,
        property_class=property_class,
        market=market,
    )

    if json_output:
        click.echo(est.model_dump_json(indent=2))
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"  RENOVATION COST ESTIMATE")
    click.echo(f"{'='*60}")
    click.echo(f"  Unit: {sqft} sf, {beds}BR/{baths}BA")
    click.echo(f"  Scope: {scope} | Finish: {finish} | Size: {est.size_category.value}")
    if year_built:
        click.echo(f"  Year Built: {year_built}")
    click.echo(f"{'='*60}\n")

    click.echo("  LINE ITEMS:")
    click.echo(f"  {'Category':<25} {'Low':>10} {'High':>10}")
    click.echo(f"  {'-'*45}")
    for li in est.line_items:
        click.echo(f"  {li.category:<25} ${li.low:>8,.0f} ${li.high:>8,.0f}")

    click.echo(f"  {'-'*45}")
    click.echo(f"  {'Subtotal':<25} ${est.subtotal_low:>8,.0f} ${est.subtotal_high:>8,.0f}")
    click.echo(f"  {'Contingency (' + str(est.contingency_pct) + '%)':<25} ${est.total_low - est.subtotal_low:>8,.0f} ${est.total_high - est.subtotal_high:>8,.0f}")
    click.echo(f"  {'='*45}")
    click.echo(f"  {'TOTAL':<25} ${est.total_low:>8,.0f} ${est.total_high:>8,.0f}")

    if est.risk_flags:
        click.echo(f"\n  RISK FLAGS:")
        for flag in est.risk_flags:
            icon = "!!" if flag.severity == "critical" else "!"
            click.echo(f"  [{icon}] {flag.message}")

    click.echo()


@cli.command()
@click.option("--cost-high", required=True, type=float, help="High-end cost estimate")
@click.option("--current-rent", required=True, type=float, help="Current monthly rent")
@click.option("--target-rent", required=True, type=float, help="Target post-renovation rent")
@click.option("--threshold", default=15.0, type=float, help="Minimum ROI % (default 15)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def roi(cost_high, current_rent, target_rent, threshold, json_output):
    """Check ROI threshold for a renovation plan."""
    result = check_roi(cost_high, current_rent, target_rent, threshold)

    if json_output:
        click.echo(result.model_dump_json(indent=2))
        return

    icon = "PASS" if result.clears_threshold else "FAIL"
    click.echo(f"\n  ROI CHECK: [{icon}]")
    click.echo(f"  Cost (high estimate): ${result.total_cost_high:,.0f}")
    click.echo(f"  Rent lift: ${result.current_monthly_rent:,.0f} → ${result.target_monthly_rent:,.0f} (+${result.monthly_rent_lift:,.0f}/mo)")
    click.echo(f"  Annual lift: ${result.annual_rent_lift:,.0f}")
    click.echo(f"  ROI: {result.roi_pct:.1f}% (threshold: {result.threshold_pct:.0f}%)")
    click.echo(f"  {result.note}\n")


@cli.command()
@click.option("--sqft", required=True, type=float, help="Unit square footage")
@click.option("--beds", required=True, type=int, help="Number of bedrooms")
@click.option("--baths", required=True, type=int, help="Number of bathrooms")
@click.option("--scope", default="standard_value_add", type=click.Choice(["light", "standard_value_add"]))
@click.option("--finish", default="basic", type=click.Choice(["basic", "upgraded"]))
@click.option("--address", default="", help="Property address")
@click.option("--unit-id", default="", help="Unit identifier")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def sow(sqft, beds, baths, scope, finish, address, unit_id, json_output):
    """Generate a scope of work for contractor bidding."""
    result = generate_sow(
        unit_sqft=sqft,
        bedrooms=beds,
        bathrooms=baths,
        scope_level=scope,
        finish_tier=finish,
        property_address=address,
        unit_id=unit_id,
    )

    if json_output:
        click.echo(result.model_dump_json(indent=2))
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"  SCOPE OF WORK")
    click.echo(f"{'='*60}")
    if result.property_address:
        click.echo(f"  Property: {result.property_address}")
    if result.unit_id:
        click.echo(f"  Unit: {result.unit_id}")
    click.echo(f"  {result.notes}")
    click.echo(f"{'='*60}\n")

    for i, li in enumerate(result.line_items, 1):
        click.echo(f"  {i}. {li.category.upper()}")
        click.echo(f"     Description: {li.description}")
        click.echo(f"     Materials: {li.material_spec}")
        click.echo(f"     Quantity: {li.quantity_notes}")
        click.echo(f"     Standard: {li.quality_standard}")
        click.echo()

    click.echo(f"  GENERAL CONDITIONS:")
    click.echo(f"  {result.general_conditions}\n")


@cli.command("evaluate-bid")
@click.option("--bid-json", required=True, type=click.Path(exists=True), help="Path to bid JSON file")
@click.option("--sqft", required=True, type=float, help="Unit square footage")
@click.option("--beds", required=True, type=int, help="Number of bedrooms")
@click.option("--baths", required=True, type=int, help="Number of bathrooms")
@click.option("--scope", default="standard_value_add", type=click.Choice(["light", "standard_value_add"]))
@click.option("--finish", default="basic", type=click.Choice(["basic", "upgraded"]))
@click.option("--year-built", type=int, default=None)
@click.option("--json-output", is_flag=True, help="Output as JSON")
def evaluate_bid_cmd(bid_json, sqft, beds, baths, scope, finish, year_built, json_output):
    """Evaluate a contractor bid against internal estimate."""
    with open(bid_json) as f:
        bid_data = json.load(f)

    bid = ContractorBid(**bid_data)
    est = estimate_unit(sqft, beds, baths, scope, finish, year_built=year_built)
    result = evaluate_bid(bid, est)

    if json_output:
        click.echo(result.model_dump_json(indent=2))
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"  BID EVALUATION: {result.contractor_name}")
    click.echo(f"{'='*60}")
    click.echo(f"  Bid Total: ${result.bid_total:,.0f}")
    click.echo(f"  Internal Estimate: ${result.internal_estimate_low:,.0f} - ${result.internal_estimate_high:,.0f}")
    click.echo(f"  Assessment: {result.overall_assessment.upper()}")
    click.echo()

    if result.flags:
        click.echo(f"  FLAGS:")
        for flag in result.flags:
            icon = "!!" if flag.severity == "critical" else "!"
            click.echo(f"  [{icon}] [{flag.flag_type}] {flag.message}")
    else:
        click.echo(f"  No flags raised — bid appears reasonable.")

    click.echo()


@cli.command("bridge-underwriting")
@click.option("--sqft", required=True, type=float, help="Unit square footage")
@click.option("--beds", required=True, type=int, help="Number of bedrooms")
@click.option("--baths", required=True, type=int, help="Number of bathrooms")
@click.option("--current-rent", required=True, type=float, help="Current monthly rent")
@click.option("--target-rent", required=True, type=float, help="Target post-renovation monthly rent")
@click.option("--start-month", required=True, type=str, help="Renovation start month (YYYY-MM)")
@click.option("--monthly-pace", required=True, type=int, help="Units renovated per month")
@click.option("--scope", default="standard_value_add", type=click.Choice(["light", "standard_value_add"]))
@click.option("--finish", default="basic", type=click.Choice(["basic", "upgraded"]))
@click.option("--year-built", type=int, default=None, help="Property year built")
@click.option("--property-class", type=click.Choice(["B", "C"]), default=None)
@click.option("--market", type=str, default=None, help="Market (dallas, birmingham)")
@click.option("--downtime-days", type=int, default=21, help="Vacancy days per unit (default 21)")
@click.option("--threshold", default=15.0, type=float, help="Minimum ROI % (default 15)")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def bridge_underwriting(
    sqft, beds, baths, current_rent, target_rent, start_month, monthly_pace,
    scope, finish, year_built, property_class, market, downtime_days,
    threshold, json_output,
):
    """Estimate unit cost, validate ROI, and produce underwriting-ready renovation program."""
    try:
        result = prepare_renovation_program(
            unit_sqft=sqft,
            bedrooms=beds,
            bathrooms=baths,
            current_monthly_rent=current_rent,
            target_monthly_rent=target_rent,
            start_month=start_month,
            monthly_pace=monthly_pace,
            scope_level=scope,
            finish_tier=finish,
            year_built=year_built,
            property_class=property_class,
            market=market,
            downtime_days=downtime_days,
            threshold_pct=threshold,
        )
    except ValueError as e:
        roi_result = e.roi_result if hasattr(e, "roi_result") else None
        if json_output and roi_result:
            click.echo(json.dumps({
                "ready_to_underwrite": False,
                "roi_result": roi_result.model_dump(),
                "error": str(e),
            }, indent=2))
        else:
            click.echo(f"\n  ROI GATE: [FAIL]")
            click.echo(f"  {e}")
            if roi_result and roi_result.path_to_pass:
                click.echo(f"\n  PATH TO PASS:")
                for step in roi_result.path_to_pass:
                    click.echo(f"    {step}")
        click.echo()
        sys.exit(1)

    if json_output:
        click.echo(result.model_dump_json(indent=2))
        return

    prog = result.renovation_program
    roi = result.roi_result

    click.echo(f"\n{'='*60}")
    click.echo(f"  UNDERWRITING BRIDGE")
    click.echo(f"{'='*60}")
    click.echo(f"  ROI Gate: [PASS] {roi.roi_pct:.1f}% (threshold: {roi.threshold_pct:.0f}%)")
    click.echo(f"  Rent lift: ${roi.current_monthly_rent:,.0f} → ${roi.target_monthly_rent:,.0f} (+${roi.monthly_rent_lift:,.0f}/mo)")
    click.echo(f"{'='*60}\n")

    click.echo(f"  RENOVATION PROGRAM (underwriting input):")
    click.echo(f"  {'renovation_cost_per_unit':<30} ${prog['renovation_cost_per_unit']:>10,.0f}")
    click.echo(f"  {'rent_premium_monthly':<30} ${prog['rent_premium_monthly']:>10,.0f}")
    click.echo(f"  {'downtime_days':<30} {prog['downtime_days']:>10}")
    click.echo(f"  {'strategy':<30} {prog['strategy']:>10}")
    click.echo(f"  {'start_month':<30} {prog['start_month']:>10}")
    click.echo(f"  {'monthly_pace':<30} {prog['monthly_pace']:>10}")

    click.echo()
