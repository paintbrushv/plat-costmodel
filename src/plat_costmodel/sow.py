"""Scope of work (SOW) generator for contractor bidding."""

from pathlib import Path

import yaml

from .models import FinishTier, ScopeLevel, ScopeOfWork, SOWLineItem

_KB_PATH = Path(__file__).resolve().parent / "data" / "knowledge_base.yaml"


def _load_kb() -> dict:
    with open(_KB_PATH) as f:
        return yaml.safe_load(f)


# Material and quality specs by finish tier and category
_SOW_SPECS = {
    ScopeLevel.STANDARD_VALUE_ADD: {
        FinishTier.BASIC: {
            "flooring": {
                "material_spec": "Standard grade LVP, 6mm+ with attached underlayment. Carpet in bedrooms (FHA-grade, stain-resistant).",
                "quality_standard": "Seams tight, no lippage >1/16\", transitions at all doorways. Carpet stretched and tacked, no wrinkles.",
            },
            "kitchen": {
                "material_spec": "Paint existing cabinets (2 coats, semi-gloss). Basic hardware (brushed nickel or matte black). Butcher block or laminate countertops.",
                "quality_standard": "Cabinet doors smooth, no drips or sags. Hardware aligned. Counters level, sealed, backsplash caulked to wall.",
            },
            "bathroom": {
                "material_spec": "Standard vanity (30-36\"), basic faucet (brushed nickel). Tub resurfacing OR new acrylic surround. Standard toilet if replacement needed.",
                "quality_standard": "Vanity level, plumbed with no leaks. Tub surface smooth and even. All fixtures operational, caulk lines clean.",
            },
            "paint": {
                "material_spec": "Interior latex, eggshell finish on walls, semi-gloss on trim/doors. 2 coats over primer where needed.",
                "quality_standard": "Full coverage, no holidays, cut lines clean, no paint on fixtures/hardware. Walls patched and sanded smooth before painting.",
            },
            "appliances": {
                "material_spec": "New basic black appliance package: refrigerator (18+ cu ft), gas/electric range, dishwasher, over-range microwave.",
                "quality_standard": "All units installed level, connected, and operational. Anti-tip bracket on range. Water line to fridge if ice maker.",
            },
            "fixtures_doors_trim": {
                "material_spec": "New light fixtures (LED, builder grade). New outlet/switch covers (white). New door hardware (lever style, matching finish).",
                "quality_standard": "All fixtures operational, properly grounded. Covers flush to wall. Hardware aligned and latching properly.",
            },
        },
        FinishTier.UPGRADED: {
            "flooring": {
                "material_spec": "Upgraded LVP throughout all rooms (no carpet), 7mm+ with rigid core. Color: modern gray/brown wood-look.",
                "quality_standard": "Seams tight, no lippage >1/16\", transitions at all doorways. Consistent plank direction throughout unit.",
            },
            "kitchen": {
                "material_spec": "Paint existing cabinets (2 coats, semi-gloss) with upgraded hardware (modern bar pulls). Granite countertops. Tile backsplash (subway or equivalent).",
                "quality_standard": "Cabinet doors smooth, no drips. Granite seams minimal and color-matched. Backsplash grout lines even, sealed. Hardware aligned.",
            },
            "bathroom": {
                "material_spec": "Upgraded vanity (36\"+, soft-close drawers). Upgraded faucet (matte black or brushed gold). New tub surround or tile surround. Framed mirror.",
                "quality_standard": "Vanity level, soft-close functional. Tile grout even and sealed. Mirror centered over vanity. All fixtures leak-free.",
            },
            "paint": {
                "material_spec": "Interior latex, eggshell finish on walls, semi-gloss on trim/doors. 2 coats over primer. Accent wall option available.",
                "quality_standard": "Full coverage, no holidays, cut lines clean, no paint on fixtures/hardware. Walls patched and sanded smooth before painting.",
            },
            "appliances": {
                "material_spec": "New stainless steel appliance package: refrigerator (18+ cu ft), gas/electric range, dishwasher, over-range microwave.",
                "quality_standard": "All units installed level, connected, and operational. Anti-tip bracket on range. Water line to fridge if ice maker. Stainless surfaces free of scratches.",
            },
            "fixtures_doors_trim": {
                "material_spec": "Upgraded light fixtures (modern LED). New outlet/switch covers (white or matching). New door hardware (modern lever, matte black or brushed nickel).",
                "quality_standard": "All fixtures operational, properly grounded. Covers flush to wall. Hardware aligned, latching properly, consistent finish throughout.",
            },
        },
    },
    ScopeLevel.LIGHT: {
        FinishTier.BASIC: {
            "paint": {
                "material_spec": "Touch-up or single coat interior latex, eggshell on walls.",
                "quality_standard": "Even coverage, clean cut lines. Patch and sand any holes or damage before painting.",
            },
            "cleaning": {
                "material_spec": "Professional deep clean: all surfaces, appliances (interior/exterior), windows, carpet shampoo.",
                "quality_standard": "Move-in ready. No dust, stains, or odors. Carpets free of visible stains.",
            },
            "patch_repair": {
                "material_spec": "Drywall patches, nail hole fill, minor caulking, weatherstrip replacement as needed.",
                "quality_standard": "Patches sanded smooth and painted to match. Caulk lines clean. No visible damage remaining.",
            },
            "hardware": {
                "material_spec": "New cabinet/door hardware and outlet/switch covers as needed.",
                "quality_standard": "All hardware functional, aligned, consistent finish.",
            },
            "carpet": {
                "material_spec": "Replace carpet in bedrooms if worn (FHA-grade, stain-resistant). Clean if serviceable.",
                "quality_standard": "Carpet stretched and tacked, no wrinkles or bumps. Seams invisible.",
            },
        },
    },
}


def generate_sow(
    unit_sqft: float,
    bedrooms: int,
    bathrooms: int,
    scope_level: ScopeLevel | str,
    finish_tier: FinishTier | str = FinishTier.BASIC,
    property_address: str = "",
    unit_id: str = "",
) -> ScopeOfWork:
    """Generate a detailed scope of work document for contractor bidding."""
    scope_level = ScopeLevel(scope_level)
    finish_tier = FinishTier(finish_tier)

    kb = _load_kb()
    scope_data = kb["scope_levels"][scope_level.value]

    # Light scope only has basic tier specs
    tier_key = finish_tier if scope_level == ScopeLevel.STANDARD_VALUE_ADD else FinishTier.BASIC
    specs = _SOW_SPECS.get(scope_level, {}).get(tier_key, {})

    line_items: list[SOWLineItem] = []
    for cat_name, item_data in scope_data["line_items"].items():
        if cat_name == "contingency_pct":
            continue

        spec = specs.get(cat_name, {})
        per = item_data.get("per", "")
        qty_note = f"{bathrooms} bathroom(s)" if per == "bathroom" else f"Entire unit (~{unit_sqft} sf, {bedrooms}BR/{bathrooms}BA)"

        line_items.append(SOWLineItem(
            category=cat_name,
            description=item_data.get("notes", ""),
            material_spec=spec.get("material_spec", item_data.get("material", "")),
            quantity_notes=qty_note,
            quality_standard=spec.get("quality_standard", "Per industry standard."),
        ))

    general_conditions = (
        "Contractor responsible for: dumpster/debris removal, daily cleanup, "
        "protection of existing finishes not being replaced, all permits as required. "
        "All work to comply with local building codes. "
        "Warranty: 1 year on workmanship from completion date."
    )

    return ScopeOfWork(
        property_address=property_address,
        unit_id=unit_id,
        scope_level=scope_level,
        finish_tier=finish_tier,
        line_items=line_items,
        general_conditions=general_conditions,
        notes=f"Unit: ~{unit_sqft} sf, {bedrooms}BR/{bathrooms}BA. "
              f"Scope: {scope_level.value}. Finish: {finish_tier.value}.",
    )
