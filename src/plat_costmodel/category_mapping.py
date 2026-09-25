"""Yardi GL account code and description → standardized rehab category mapping.

This module is the translation layer between Yardi Voyager's GL coding scheme and the
internal standardized categories used by the plat-costmodel estimator.

Mapping priority (highest to lowest):
  1. Exact GL account code match
  2. GL account code range match
  3. Normalized description / category name keyword match
  4. Fallback → "other"

Standardized internal categories
---------------------------------
Interior unit-level (standard value-add scope):
  flooring          LVP, carpet, tile
  kitchen           Cabinets, counters, backsplash
  bathroom          Vanity, tub, shower, toilet, fixtures
  paint             Interior painting
  appliances        Fridge, stove, dishwasher, microwave
  fixtures_doors_trim  Light fixtures, switch plates, door hardware

Interior unit-level (light scope only):
  cleaning          Deep clean / carpet clean
  patch_repair      Drywall patch, minor repairs
  hardware          Cabinet/door hardware

Building systems (interior or property-wide):
  hvac              Heating, cooling, mini-splits
  plumbing          Pipes, water heater, drains
  electrical        Panel, wiring, outlets

Exterior / CapEx (property-level):
  roof              Roof replacement or major repair
  parking           Parking lot reseal / resurface
  siding_paint      Exterior paint, siding, stucco
  fencing_gates     Fencing, gates, security entries
  landscaping       Landscaping overhaul, irrigation
  signage_lighting  Property signage, exterior lighting

Unclassified:
  other             Anything not matched above
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Internal category constants — single source of truth for all category names
# ---------------------------------------------------------------------------

INTERIOR_UNIT_CATEGORIES = frozenset({
    "flooring",
    "kitchen",
    "bathroom",
    "paint",
    "appliances",
    "fixtures_doors_trim",
    # Light-scope only
    "cleaning",
    "patch_repair",
    "hardware",
    "carpet",
})

SYSTEMS_CATEGORIES = frozenset({
    "hvac",
    "plumbing",
    "electrical",
})

EXTERIOR_CAPEX_CATEGORIES = frozenset({
    "roof",
    "parking",
    "siding_paint",
    "fencing_gates",
    "landscaping",
    "signage_lighting",
})

ALL_CATEGORIES = INTERIOR_UNIT_CATEGORIES | SYSTEMS_CATEGORIES | EXTERIOR_CAPEX_CATEGORIES | {"other"}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MappingResult:
    """Result of mapping a Yardi GL entry to an internal category.

    Attributes:
        internal_category: Standardized category name (see module docstring).
        source: How the match was made — one of:
                "gl_exact"    — Exact GL account code match
                "gl_range"    — GL code fell within a defined range
                "description" — Matched on description/category text keyword
                "fallback"    — No match found; defaulted to "other"
        confidence: "high" (gl_exact or gl_range) | "medium" (description) | "low" (fallback)
        match_key: The specific key/pattern that triggered the match (for audit trails).
    """
    internal_category: str
    source: str
    confidence: str
    match_key: str = ""

    @property
    def is_classified(self) -> bool:
        return self.internal_category != "other"


# ---------------------------------------------------------------------------
# GL account code mappings
# ---------------------------------------------------------------------------

# Exact GL code → internal category
# These are Yardi Voyager's typical multifamily chart-of-accounts codes.
# A real operator's chart of accounts may use a subset of these; additional
# codes can be registered via CategoryMapper.register_gl_code().
_GL_EXACT: dict[str, str] = {
    # ── Turnover / Make-Ready (5000 series) ──────────────────────────────
    "5000": "patch_repair",      # Turnover - General
    "5005": "cleaning",          # Turnover - Cleaning / janitorial
    "5010": "patch_repair",      # Make-ready labor (general repairs/touch-ups)
    "5015": "paint",             # Make-ready painting
    "5020": "flooring",          # Make-ready flooring
    "5025": "carpet",            # Make-ready carpet replacement
    "5030": "appliances",        # Make-ready appliance replacement
    "5035": "hardware",          # Make-ready hardware / fixtures
    "5040": "kitchen",           # Make-ready kitchen
    "5045": "bathroom",          # Make-ready bathroom
    "5050": "fixtures_doors_trim", # Make-ready doors / trim / light fixtures

    # ── Repairs & Maintenance (5100 series) ──────────────────────────────
    "5100": "patch_repair",      # R&M - General
    "5105": "plumbing",          # R&M - Plumbing
    "5110": "electrical",        # R&M - Electrical
    "5115": "hvac",              # R&M - HVAC
    "5120": "appliances",        # R&M - Appliances
    "5125": "flooring",          # R&M - Flooring repairs
    "5130": "paint",             # R&M - Interior painting
    "5135": "kitchen",           # R&M - Kitchen
    "5140": "bathroom",          # R&M - Bathroom
    "5150": "roof",              # R&M - Roof repairs (minor; major = CapEx)
    "5155": "siding_paint",      # R&M - Exterior paint / siding
    "5160": "fencing_gates",     # R&M - Fencing / gates
    "5165": "parking",           # R&M - Parking lot / pavement
    "5170": "landscaping",       # R&M - Landscaping
    "5175": "signage_lighting",  # R&M - Signage / exterior lighting

    # ── Contract Services (5200 series) ──────────────────────────────────
    "5200": "cleaning",          # Contract - Janitorial / cleaning
    "5205": "landscaping",       # Contract - Landscaping
    "5210": "hvac",              # Contract - HVAC maintenance
    "5215": "electrical",        # Contract - Electrical (contracted)
    "5220": "plumbing",          # Contract - Plumbing (contracted)
    "5230": "pest_control",      # Contract - Pest control (→ other; not a rehab category)
    "5240": "signage_lighting",  # Contract - Exterior lighting maintenance
    "5250": "roof",              # Contract - Roofing (repairs under service contract)

    # ── Capital Expenditures (5300 series) ───────────────────────────────
    "5300": "patch_repair",      # CapEx - General interior
    "5305": "flooring",          # CapEx - Flooring (unit)
    "5310": "kitchen",           # CapEx - Kitchen renovation
    "5315": "bathroom",          # CapEx - Bathroom renovation
    "5320": "appliances",        # CapEx - Appliance package
    "5325": "hvac",              # CapEx - HVAC replacement (unit)
    "5330": "plumbing",          # CapEx - Plumbing replacement
    "5335": "electrical",        # CapEx - Electrical upgrade
    "5340": "fixtures_doors_trim", # CapEx - Fixtures / doors / trim
    "5345": "paint",             # CapEx - Interior painting (full unit)
    "5350": "roof",              # CapEx - Roof replacement
    "5355": "parking",           # CapEx - Parking reseal / resurface
    "5360": "hvac",              # CapEx - HVAC replacement (building)
    "5365": "siding_paint",      # CapEx - Exterior paint / siding
    "5370": "fencing_gates",     # CapEx - Fencing / gates / security
    "5375": "landscaping",       # CapEx - Landscaping overhaul
    "5380": "signage_lighting",  # CapEx - Signage / exterior lighting
    "5385": "electrical",        # CapEx - Electrical panel / building
    "5390": "plumbing",          # CapEx - Underground plumbing / mains
    "5395": "patch_repair",      # CapEx - Foundation / structural (conservative: flag, don't estimate)

    # ── Alternative 4-digit scheme (some Yardi configs use 4xxx for CapEx) ─
    "4300": "flooring",
    "4305": "kitchen",
    "4310": "bathroom",
    "4315": "appliances",
    "4320": "hvac",
    "4325": "plumbing",
    "4330": "electrical",
    "4350": "roof",
    "4355": "parking",
    "4360": "siding_paint",
    "4365": "fencing_gates",
    "4370": "landscaping",
    "4375": "signage_lighting",
}

# Remap pest_control (not a rehab category) to "other"
_GL_EXACT = {k: (v if v in ALL_CATEGORIES else "other") for k, v in _GL_EXACT.items()}


# GL code RANGE rules: (low_inclusive, high_inclusive, category)
# Applied in order; first match wins.
_GL_RANGES: list[tuple[int, int, str]] = [
    # Turnover / make-ready → unit interior
    (5000, 5009, "patch_repair"),
    (5010, 5029, "flooring"),
    (5030, 5039, "appliances"),
    (5040, 5049, "kitchen"),
    (5050, 5059, "fixtures_doors_trim"),
    # General R&M → interior
    (5100, 5104, "patch_repair"),
    (5105, 5109, "plumbing"),
    (5110, 5114, "electrical"),
    (5115, 5119, "hvac"),
    (5120, 5129, "appliances"),
    (5130, 5134, "paint"),
    (5135, 5139, "kitchen"),
    (5140, 5149, "bathroom"),
    # Exterior R&M
    (5150, 5154, "roof"),
    (5155, 5159, "siding_paint"),
    (5160, 5164, "fencing_gates"),
    (5165, 5169, "parking"),
    (5170, 5174, "landscaping"),
    (5175, 5179, "signage_lighting"),
    # Contract services
    (5200, 5209, "cleaning"),
    (5210, 5219, "hvac"),
    (5220, 5229, "plumbing"),
    (5240, 5249, "signage_lighting"),
    (5250, 5259, "roof"),
    # CapEx — interior
    (5300, 5304, "patch_repair"),
    (5305, 5309, "flooring"),
    (5310, 5314, "kitchen"),
    (5315, 5319, "bathroom"),
    (5320, 5324, "appliances"),
    (5325, 5329, "hvac"),
    (5330, 5334, "plumbing"),
    (5335, 5339, "electrical"),
    (5340, 5344, "fixtures_doors_trim"),
    (5345, 5349, "paint"),
    # CapEx — exterior
    (5350, 5354, "roof"),
    (5355, 5359, "parking"),
    (5360, 5364, "hvac"),
    (5365, 5369, "siding_paint"),
    (5370, 5374, "fencing_gates"),
    (5375, 5379, "landscaping"),
    (5380, 5384, "signage_lighting"),
    (5385, 5399, "electrical"),
    # 4xxx CapEx alternative scheme
    (4300, 4319, "flooring"),
    (4320, 4334, "hvac"),
    (4335, 4349, "electrical"),
    (4350, 4354, "roof"),
    (4355, 4359, "parking"),
    (4360, 4364, "siding_paint"),
    (4365, 4369, "fencing_gates"),
    (4370, 4374, "landscaping"),
    (4375, 4399, "signage_lighting"),
]


def _assert_gl_ranges_no_overlap(ranges: list[tuple[int, int, str]]) -> None:
    """Validate that no two GL-code ranges overlap.

    Overlapping ranges silently produce ``first-match-wins`` resolution and
    bury custom mappings registered via ``CategoryMapper.register_gl_code``.
    Per Wave 2 Bug 2.7 fix: this invariant is enforced at module import so a
    bad addition fails loudly rather than corrupting historical classifications.

    Raises:
        ValueError: if any (low, high) pair overlaps any other.
    """
    # First validate per-range well-formedness (low <= high).
    for low, high, cat in ranges:
        if low > high:
            raise ValueError(
                f"GL range invalid: low > high for ({low}, {high}, '{cat}')"
            )
    sorted_ranges = sorted(ranges, key=lambda r: (r[0], r[1]))
    for i in range(len(sorted_ranges) - 1):
        low1, high1, cat1 = sorted_ranges[i]
        low2, high2, cat2 = sorted_ranges[i + 1]
        if low2 <= high1:
            raise ValueError(
                f"GL range overlap detected: ({low1}-{high1}, '{cat1}') overlaps "
                f"({low2}-{high2}, '{cat2}'). Ranges must be disjoint to avoid "
                f"first-match-wins ambiguity."
            )


# Sort for deterministic, longest-range-last iteration. Longer-pattern wins
# is achieved by sorting by descending range-width so a more specific (narrower)
# range can never be silently swallowed by a broader one if accidentally added
# later. Ranges must be disjoint (asserted on import).
_GL_RANGES.sort(key=lambda r: (r[1] - r[0], r[0]))
_assert_gl_ranges_no_overlap(_GL_RANGES)


# ---------------------------------------------------------------------------
# Description / category name keyword mappings
# ---------------------------------------------------------------------------
# Each entry: (keyword_pattern, internal_category)
# Matched against the lowercased, stripped input string using substring search.
# Order matters: more specific patterns should come before broader ones.

_DESCRIPTION_KEYWORDS: list[tuple[str, str]] = [
    # ── Flooring ───────────────────────────────────────────────────────────
    ("luxury vinyl plank", "flooring"),
    ("lvp", "flooring"),
    ("vinyl plank", "flooring"),
    ("vinyl flooring", "flooring"),
    ("laminate floor", "flooring"),
    ("hardwood floor", "flooring"),
    ("tile floor", "flooring"),
    ("floor tile", "flooring"),
    ("subfloor", "flooring"),
    ("sub-floor", "flooring"),
    ("flooring", "flooring"),
    ("floor install", "flooring"),

    # ── Carpet (separate from flooring for light-scope) ────────────────────
    ("carpet clean", "cleaning"),
    ("carpet shampoo", "cleaning"),
    ("carpet steam", "cleaning"),
    ("carpet replacement", "carpet"),
    ("carpet replace", "carpet"),
    ("carpet install", "carpet"),
    ("carpet", "carpet"),

    # ── Kitchen ────────────────────────────────────────────────────────────
    ("cabinet paint", "kitchen"),
    ("cabinet refac", "kitchen"),
    ("cabinet replac", "kitchen"),
    ("cabinet", "kitchen"),
    ("countertop", "kitchen"),
    ("counter top", "kitchen"),
    ("butcher block", "kitchen"),
    ("granite counter", "kitchen"),
    ("backsplash", "kitchen"),
    ("kitchen renovation", "kitchen"),
    ("kitchen reno", "kitchen"),
    ("kitchen update", "kitchen"),
    ("kitchen remodel", "kitchen"),
    ("kitchen", "kitchen"),

    # ── Bathroom ───────────────────────────────────────────────────────────
    ("tub resurface", "bathroom"),
    ("tub refinish", "bathroom"),
    ("tub surround", "bathroom"),
    ("bathtub", "bathroom"),
    ("tub ", "bathroom"),
    ("shower surround", "bathroom"),
    ("shower pan", "bathroom"),
    ("shower tile", "bathroom"),
    ("shower", "bathroom"),
    ("vanity", "bathroom"),
    ("toilet replac", "bathroom"),
    ("toilet", "bathroom"),
    ("bath fixture", "bathroom"),
    ("bathroom reno", "bathroom"),
    ("bathroom remodel", "bathroom"),
    ("bathroom update", "bathroom"),
    ("bath reno", "bathroom"),
    ("bath remodel", "bathroom"),
    ("bathroom", "bathroom"),
    ("bath ", "bathroom"),

    # ── Paint ──────────────────────────────────────────────────────────────
    ("interior paint", "paint"),
    ("exterior paint", "siding_paint"),  # Exterior → different category
    ("2-coat paint", "paint"),
    ("two coat paint", "paint"),
    ("paint labor", "paint"),
    ("paint material", "paint"),
    ("paint ", "paint"),
    ("painting", "paint"),
    ("repaint", "paint"),

    # ── Appliances ─────────────────────────────────────────────────────────
    ("appliance package", "appliances"),
    ("appliance set", "appliances"),
    ("refrigerator", "appliances"),
    ("fridge", "appliances"),
    ("stove replac", "appliances"),
    ("range replac", "appliances"),
    ("dishwasher", "appliances"),
    ("microwave", "appliances"),
    ("washer/dryer", "appliances"),
    ("washer dryer", "appliances"),
    ("w/d", "appliances"),
    ("appliance", "appliances"),
    ("stove", "appliances"),
    ("oven", "appliances"),

    # ── Fixtures / doors / trim ────────────────────────────────────────────
    ("light fixture", "fixtures_doors_trim"),
    ("lighting fixture", "fixtures_doors_trim"),
    ("outlet cover", "fixtures_doors_trim"),
    ("switch plate", "fixtures_doors_trim"),
    ("door hardware", "fixtures_doors_trim"),
    ("door knob", "fixtures_doors_trim"),
    ("door replac", "fixtures_doors_trim"),
    ("door install", "fixtures_doors_trim"),
    ("interior door", "fixtures_doors_trim"),
    ("trim install", "fixtures_doors_trim"),
    ("baseboard", "fixtures_doors_trim"),
    ("crown molding", "fixtures_doors_trim"),
    ("hardware", "hardware"),   # Generic hardware → light scope
    ("fixture", "fixtures_doors_trim"),
    ("door ", "fixtures_doors_trim"),

    # ── Cleaning ───────────────────────────────────────────────────────────
    ("deep clean", "cleaning"),
    ("move-out clean", "cleaning"),
    ("move out clean", "cleaning"),
    ("unit clean", "cleaning"),
    ("janitorial", "cleaning"),
    ("cleaning service", "cleaning"),
    ("clean unit", "cleaning"),
    ("cleaning", "cleaning"),

    # ── Patch / repair ─────────────────────────────────────────────────────
    ("drywall patch", "patch_repair"),
    ("drywall repair", "patch_repair"),
    ("plaster repair", "patch_repair"),
    ("wall repair", "patch_repair"),
    ("hole repair", "patch_repair"),
    ("caulk", "patch_repair"),
    ("grout repair", "patch_repair"),
    ("touch-up repair", "patch_repair"),
    ("minor repair", "patch_repair"),
    ("general repair", "patch_repair"),
    ("make-ready", "patch_repair"),
    ("make ready", "patch_repair"),
    ("unit turn", "patch_repair"),
    ("unit turnover", "patch_repair"),
    ("patch", "patch_repair"),
    ("repair", "patch_repair"),

    # ── HVAC ───────────────────────────────────────────────────────────────
    ("hvac replac", "hvac"),
    ("hvac install", "hvac"),
    ("hvac repair", "hvac"),
    ("hvac service", "hvac"),
    ("mini split", "hvac"),
    ("heat pump", "hvac"),
    ("air handler", "hvac"),
    ("air conditioning", "hvac"),
    ("a/c unit", "hvac"),
    ("ac unit", "hvac"),
    ("furnace", "hvac"),
    ("boiler", "hvac"),
    ("hvac", "hvac"),
    ("heating", "hvac"),
    ("cooling", "hvac"),

    # ── Plumbing ───────────────────────────────────────────────────────────
    ("water heater", "plumbing"),
    ("hot water heater", "plumbing"),
    ("galvanized pipe", "plumbing"),
    ("cast iron drain", "plumbing"),
    ("drain line", "plumbing"),
    ("sewer line", "plumbing"),
    ("water main", "plumbing"),
    ("supply line", "plumbing"),
    ("plumbing replac", "plumbing"),
    ("plumbing repair", "plumbing"),
    ("leak repair", "plumbing"),
    ("plumbing", "plumbing"),
    ("pipe", "plumbing"),

    # ── Electrical ─────────────────────────────────────────────────────────
    ("electrical panel", "electrical"),
    ("panel upgrade", "electrical"),
    ("panel replac", "electrical"),
    ("breaker box", "electrical"),
    ("wiring replac", "electrical"),
    ("rewire", "electrical"),
    ("gfci", "electrical"),
    ("outlet replac", "electrical"),
    ("electrical repair", "electrical"),
    ("electrical", "electrical"),
    ("wiring", "electrical"),

    # ── Roof ───────────────────────────────────────────────────────────────
    ("roof replac", "roof"),
    ("roof repair", "roof"),
    ("roof install", "roof"),
    ("shingle", "roof"),
    ("membrane roof", "roof"),
    ("flat roof", "roof"),
    ("roofing", "roof"),
    ("roof", "roof"),

    # ── Parking ────────────────────────────────────────────────────────────
    ("parking lot", "parking"),
    ("parking reseal", "parking"),
    ("asphalt reseal", "parking"),
    ("asphalt resurface", "parking"),
    ("parking resurface", "parking"),
    ("lot striping", "parking"),
    ("parking strip", "parking"),
    ("driveway reseal", "parking"),
    ("asphalt", "parking"),
    ("pavement", "parking"),
    ("paving", "parking"),
    ("parking", "parking"),

    # ── Siding / exterior paint ────────────────────────────────────────────
    ("siding replac", "siding_paint"),
    ("siding repair", "siding_paint"),
    ("stucco replac", "siding_paint"),
    ("stucco repair", "siding_paint"),
    ("exterior repaint", "siding_paint"),
    ("building paint", "siding_paint"),
    ("siding", "siding_paint"),
    ("stucco", "siding_paint"),

    # ── Fencing / gates ────────────────────────────────────────────────────
    ("fence replac", "fencing_gates"),
    ("fence repair", "fencing_gates"),
    ("fence install", "fencing_gates"),
    ("gate replac", "fencing_gates"),
    ("gate install", "fencing_gates"),
    ("security gate", "fencing_gates"),
    ("access gate", "fencing_gates"),
    ("fencing", "fencing_gates"),
    ("fence", "fencing_gates"),
    ("gate", "fencing_gates"),

    # ── Landscaping ────────────────────────────────────────────────────────
    ("landscape overhaul", "landscaping"),
    ("landscape install", "landscaping"),
    ("sod install", "landscaping"),
    ("irrigation", "landscaping"),
    ("mulch", "landscaping"),
    ("tree trimm", "landscaping"),
    ("tree remov", "landscaping"),
    ("landscaping", "landscaping"),
    ("landscape", "landscaping"),

    # ── Signage / exterior lighting ────────────────────────────────────────
    ("monument sign", "signage_lighting"),
    ("property sign", "signage_lighting"),
    ("entry sign", "signage_lighting"),
    ("exterior light", "signage_lighting"),
    ("parking light", "signage_lighting"),
    ("pole light", "signage_lighting"),
    ("led retrofit", "signage_lighting"),
    ("signage", "signage_lighting"),
    ("lighting upgrade", "signage_lighting"),
    ("lighting", "signage_lighting"),
    ("sign", "signage_lighting"),
]


# ---------------------------------------------------------------------------
# CategoryMapper class
# ---------------------------------------------------------------------------

class CategoryMapper:
    """Maps Yardi GL account codes and descriptions to standardized rehab categories.

    Usage::

        mapper = CategoryMapper()

        # Map by GL account code only
        result = mapper.map(gl_code="5320")
        # → MappingResult(internal_category="appliances", source="gl_exact", ...)

        # Map by description only
        result = mapper.map(description="LVP flooring install")
        # → MappingResult(internal_category="flooring", source="description", ...)

        # Map by both — GL code wins if present
        result = mapper.map(gl_code="5100", description="general repairs")
        # → MappingResult(internal_category="patch_repair", source="gl_exact", ...)

        # Register a custom GL code for a specific chart-of-accounts
        mapper.register_gl_code("5999", "flooring")
    """

    def __init__(
        self,
        extra_gl_codes: Optional[dict[str, str]] = None,
        extra_keywords: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        """Initialise the mapper with optional custom extensions.

        Args:
            extra_gl_codes: Dict of {gl_code_str: internal_category} to add on top
                            of the built-in mappings.
            extra_keywords: List of (keyword, internal_category) pairs to prepend
                            to the description keyword list (higher priority).
        """
        self._gl_exact: dict[str, str] = dict(_GL_EXACT)
        if extra_gl_codes:
            for code, cat in extra_gl_codes.items():
                self.register_gl_code(code, cat)

        # Description keyword resolution is longest-substring-first to avoid
        # order-dependent first-match-wins ambiguity (Wave 2 Bug 2.7 fix).
        # ``extra_keywords`` retain priority over the built-ins (so callers can
        # override), but within each tier we sort by descending pattern length.
        # Example: "Security Contract Services" matches "security gate"-grade
        # patterns before falling through to the broader "contract services"
        # bucket; "door hardware" wins over the generic "hardware" rule.
        extras = sorted(list(extra_keywords or []), key=lambda kv: -len(kv[0]))
        builtins = sorted(list(_DESCRIPTION_KEYWORDS), key=lambda kv: -len(kv[0]))
        self._keywords: list[tuple[str, str]] = extras + builtins

    # ── Public API ──────────────────────────────────────────────────────

    def register_gl_code(self, gl_code: str, internal_category: str) -> None:
        """Register a custom GL account code mapping.

        Args:
            gl_code: Yardi GL account code string (e.g. "5999").
            internal_category: Internal category name from ALL_CATEGORIES.

        Raises:
            ValueError: If internal_category is not a recognized category.
        """
        if internal_category not in ALL_CATEGORIES:
            raise ValueError(
                f"Unknown internal category '{internal_category}'. "
                f"Valid categories: {sorted(ALL_CATEGORIES)}"
            )
        self._gl_exact[gl_code.strip()] = internal_category

    def map(
        self,
        gl_code: Optional[str] = None,
        description: Optional[str] = None,
        category_name: Optional[str] = None,
    ) -> MappingResult:
        """Map a Yardi GL entry to an internal category.

        Args:
            gl_code: Yardi GL account code (e.g. "5320", "5320.00").
            description: Free-text description of the expense line item.
            category_name: Yardi expense category field (e.g. "Flooring", "HVAC").

        Returns:
            MappingResult with internal_category, source, confidence, match_key.

        Priority:
            1. gl_code exact match
            2. gl_code range match
            3. category_name keyword match
            4. description keyword match
            5. fallback → "other"
        """
        # 1. GL exact match
        if gl_code:
            result = self._try_gl_exact(gl_code)
            if result:
                return result

            # 2. GL range match
            result = self._try_gl_range(gl_code)
            if result:
                return result

        # 3. Category name keyword match (higher signal than free-text description)
        if category_name:
            result = self._try_keyword(category_name, field="category_name")
            if result:
                return result

        # 4. Description keyword match
        if description:
            result = self._try_keyword(description, field="description")
            if result:
                return result

        # 5. Fallback
        return MappingResult(
            internal_category="other",
            source="fallback",
            confidence="low",
            match_key="",
        )

    def map_yardi_row(self, row: dict) -> MappingResult:
        """Convenience method to map a parsed Yardi CSV row.

        Looks for common Yardi column names automatically:
          GL code:     "GL Account", "GL Code", "Account Code", "Account #"
          Category:    "Category", "Expense Category", "GL Description"
          Description: "Description", "Memo", "Notes"

        Args:
            row: Dict representing one CSV row.

        Returns:
            MappingResult.
        """
        gl_code = (
            row.get("GL Account")
            or row.get("GL Code")
            or row.get("Account Code")
            or row.get("Account #")
            or row.get("Account")
            or ""
        )
        category_name = (
            row.get("Category")
            or row.get("Expense Category")
            or row.get("GL Description")
            or ""
        )
        description = (
            row.get("Description")
            or row.get("Memo")
            or row.get("Notes")
            or ""
        )
        return self.map(
            gl_code=str(gl_code).strip() or None,
            description=str(description).strip() or None,
            category_name=str(category_name).strip() or None,
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _try_gl_exact(self, gl_code: str) -> Optional[MappingResult]:
        """Attempt exact GL code match.

        Normalises the code by stripping whitespace and removing decimal suffixes
        (e.g. "5320.00" → "5320", "5320-001" → "5320").
        """
        normalised = _normalise_gl_code(gl_code)
        if not normalised:
            return None
        cat = self._gl_exact.get(normalised)
        if cat:
            return MappingResult(
                internal_category=cat,
                source="gl_exact",
                confidence="high",
                match_key=normalised,
            )
        return None

    def _try_gl_range(self, gl_code: str) -> Optional[MappingResult]:
        """Attempt GL code range match."""
        normalised = _normalise_gl_code(gl_code)
        if not normalised:
            return None
        try:
            code_int = int(normalised)
        except ValueError:
            return None

        for low, high, cat in _GL_RANGES:
            if low <= code_int <= high:
                return MappingResult(
                    internal_category=cat,
                    source="gl_range",
                    confidence="high",
                    match_key=f"{low}-{high}",
                )
        return None

    def _try_keyword(self, text: str, field: str) -> Optional[MappingResult]:
        """Attempt keyword match against a text string."""
        normalised = text.lower().strip()
        if not normalised:
            return None

        # First try exact internal category name (normalised input IS a category)
        normalised_as_cat = normalised.replace(" ", "_").replace("-", "_")
        if normalised_as_cat in ALL_CATEGORIES:
            return MappingResult(
                internal_category=normalised_as_cat,
                source="description",
                confidence="high",
                match_key=normalised_as_cat,
            )

        # Keyword substring search
        for keyword, cat in self._keywords:
            if keyword in normalised:
                return MappingResult(
                    internal_category=cat,
                    source="description",
                    confidence="medium",
                    match_key=keyword,
                )
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _normalise_gl_code(gl_code: str) -> str:
    """Strip a GL code to its numeric core.

    Examples:
        "5320"      → "5320"
        "5320.00"   → "5320"
        "5320-001"  → "5320"
        " 5320 "    → "5320"
        "05320"     → "5320"
        "53xx"      → "" (non-numeric; cannot normalise)
    """
    s = gl_code.strip()
    # Remove trailing decimal suffix
    if "." in s:
        s = s.split(".")[0]
    # Remove sub-account suffix after dash
    if "-" in s:
        s = s.split("-")[0]
    # Must be purely numeric now
    s = s.strip()
    if not s.isdigit():
        return ""
    # Strip leading zeros
    return str(int(s))


# ---------------------------------------------------------------------------
# Module-level singleton (convenience for callers that don't need customisation)
# ---------------------------------------------------------------------------

_DEFAULT_MAPPER = CategoryMapper()


def map_yardi_entry(
    gl_code: Optional[str] = None,
    description: Optional[str] = None,
    category_name: Optional[str] = None,
) -> MappingResult:
    """Map a Yardi GL entry using the default mapper (no custom extensions).

    This is a thin convenience wrapper around CategoryMapper.map().

    Args:
        gl_code: Yardi GL account code string.
        description: Free-text expense description.
        category_name: Yardi expense category field.

    Returns:
        MappingResult with internal_category and mapping provenance.
    """
    return _DEFAULT_MAPPER.map(
        gl_code=gl_code,
        description=description,
        category_name=category_name,
    )


def get_all_categories() -> frozenset[str]:
    """Return the complete set of valid internal category names."""
    return ALL_CATEGORIES


def get_interior_categories() -> frozenset[str]:
    """Return only interior unit-level category names."""
    return INTERIOR_UNIT_CATEGORIES


def get_exterior_categories() -> frozenset[str]:
    """Return only exterior / CapEx category names."""
    return EXTERIOR_CAPEX_CATEGORIES


def get_systems_categories() -> frozenset[str]:
    """Return only building systems category names."""
    return SYSTEMS_CATEGORIES
