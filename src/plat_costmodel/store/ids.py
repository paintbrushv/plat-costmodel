"""ID minting + identity-resolution helpers.

ULIDs everywhere — 26-char Crockford base32, time-sortable, globally
unique without a sequence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ulid import ULID

from plat_costmodel.schemas import AmenityInventory, FloorPlan, Property, raise_problem

if TYPE_CHECKING:
    from plat_costmodel.store.repo import PropertyRepo


def new_ulid() -> str:
    """Mint a new ULID as a string."""
    return str(ULID())


def resolve_property(repo: PropertyRepo, payload: dict) -> Property:
    """Resolve a Property by id-or-alias, creating if neither matches.

    Resolution rules:
      1. ``payload["property_id"]`` set → look up by ID. Raise ValidationProblem
         (error_type=not_found) if missing. If ``payload["external_alias"]``
         is also set and conflicts with the stored alias, raise
         validation_error — silently ignoring the caller's alias was a
         data-integrity hazard (followup #5). NOTE: when the stored row
         has ``external_alias = None`` and the caller supplies one, the
         supplied alias is currently NOT written back to the row (the
         function returns the existing row unchanged). If a caller needs
         to associate a new alias with an existing row, they must update
         the row directly via PropertyRepo. This is a known limitation;
         see the ``test_resolve_property_id_with_alias_when_stored_alias_is_none``
         test for the lock-down assertion.
      2. ``payload["external_alias"]`` set (and no property_id) → return
         existing match if found.
      3. Otherwise (or no match by alias): create a new Property with a
         minted ULID, optionally storing the alias and amenities.

    The ``payload`` dict accepts the same keys as the Property schema:
    ``property_id``, ``external_alias``, ``address``, ``market``,
    ``year_built``, ``property_class``, ``building_type``, ``total_units``,
    ``amenities``.
    """
    pid = payload.get("property_id")
    alias = payload.get("external_alias")
    if pid:
        existing = repo.get(pid)
        if existing is None:
            raise_problem(
                "not_found", f"property_id {pid} not found",
                field_errors=[{"loc": ["property_id"], "msg": "not found"}],
            )
        # Conflict check: caller supplied both property_id and external_alias,
        # and the stored property's alias differs from the supplied one.
        if (
            alias
            and existing.external_alias is not None
            and existing.external_alias != alias
        ):
            raise_problem(
                "validation_error",
                f"property_id {pid} has stored external_alias "
                f"{existing.external_alias!r}; caller supplied {alias!r}",
                field_errors=[{
                    "loc": ["external_alias"],
                    "msg": "conflicts with stored alias on this property_id",
                }],
                hint="Either omit external_alias or pass the matching value.",
            )
        return existing
    if alias:
        existing = repo.get_by_alias(alias)
        if existing:
            return existing
    return repo.create(Property(
        property_id="",
        external_alias=alias,
        address=payload.get("address", ""),
        market=payload.get("market"),
        year_built=payload.get("year_built"),
        property_class=payload.get("property_class"),
        building_type=payload.get("building_type", ""),
        total_units=int(payload.get("total_units", 0)),
        amenities=AmenityInventory(**payload.get("amenities", {})),
    ))


def resolve_floor_plan_by_dims(
    repo: PropertyRepo,
    property_id: str,
    sqft: float,
    bedrooms: int,
    bathrooms: int,
    *,
    auto_name_prefix: str = "auto",
    name: "str | None" = None,
    notes: "str | None" = None,
    external_alias: "str | None" = None,
) -> FloorPlan:
    """Find a FloorPlan on a property by exact (sqft, beds, baths) match;
    mint a new one if none exists.

    When no existing match is found, the new FloorPlan is created with:

    * ``name`` — caller-supplied name if provided; otherwise the auto-generated
      ``{auto_name_prefix}:<sqft>sf-<beds>x<baths>`` format.
    * ``notes`` — optional free-text notes propagated to the new row.
    * ``external_alias`` — optional alias propagated to the new row.

    If an existing FloorPlan *does* match, it is returned as-is (the
    optional kwargs are not applied to existing rows).

    Used by deal_projection's cohort → floor-plan mapping and by
    ``register_property`` in server.py.
    """
    existing = repo.find_floor_plan_by_dims(property_id, sqft, bedrooms, bathrooms)
    if existing is not None:
        return existing
    sqft_str = f"{int(sqft)}" if float(sqft).is_integer() else f"{sqft}"
    resolved_name = name if name is not None else f"{auto_name_prefix}:{sqft_str}sf-{bedrooms}x{bathrooms}"
    extra: dict = {}
    if notes is not None:
        extra["notes"] = notes
    if external_alias is not None:
        extra["external_alias"] = external_alias
    return repo.create_floor_plan(FloorPlan(
        floor_plan_id="",
        property_id=property_id,
        name=resolved_name,
        sqft=sqft,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        **extra,
    ))
