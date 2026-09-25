"""Tests for ULID minting helpers."""
import pytest

from plat_costmodel.store.ids import new_ulid, resolve_property, resolve_floor_plan_by_dims
from plat_costmodel.store.repo import PropertyRepo
from plat_costmodel.schemas import Property, FloorPlan


def test_new_ulid_is_26_chars():
    assert len(new_ulid()) == 26


def test_new_ulid_unique():
    assert new_ulid() != new_ulid()


def test_new_ulid_lexicographically_sortable_in_time():
    import time
    ids = [new_ulid()]
    time.sleep(0.002)
    ids.append(new_ulid())
    assert ids == sorted(ids)


# --- resolve_property -------------------------------------------------------

def test_resolve_property_id_found(tmp_db):
    """When property_id is supplied and exists, returns that property."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=10, address="A"))
    result = resolve_property(repo, {"property_id": p.property_id})
    assert result.property_id == p.property_id


def test_resolve_property_id_missing_raises(tmp_db):
    """When property_id is supplied but not found, raises ValidationProblem."""
    repo = PropertyRepo(tmp_db)
    with pytest.raises(ValueError) as exc:
        resolve_property(repo, {"property_id": "NOPE"})
    assert hasattr(exc.value, "validation_problem")
    assert exc.value.validation_problem.error_type == "not_found"


def test_resolve_property_alias_found(tmp_db):
    """When external_alias matches an existing property, returns it."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", external_alias="oak-grove", total_units=5))
    result = resolve_property(repo, {"external_alias": "oak-grove", "total_units": 5})
    assert result.property_id == p.property_id
    # Must not create a second row.
    assert repo.get_by_alias("oak-grove").property_id == p.property_id


def test_resolve_property_alias_missing_creates(tmp_db):
    """When external_alias is supplied but unrecognised, mints a new property."""
    repo = PropertyRepo(tmp_db)
    result = resolve_property(repo, {
        "external_alias": "brand-new", "total_units": 8, "address": "8 Elm St",
    })
    assert result.property_id != ""
    assert result.external_alias == "brand-new"
    assert result.address == "8 Elm St"


def test_resolve_property_no_id_no_alias_creates(tmp_db):
    """When neither property_id nor external_alias is given, mints a new property."""
    repo = PropertyRepo(tmp_db)
    result = resolve_property(repo, {"total_units": 3, "address": "3 Pine Ave"})
    assert result.property_id != ""
    assert result.external_alias is None
    assert result.address == "3 Pine Ave"


def test_resolve_property_threads_amenities_through(tmp_db):
    """Followup: amenities supplied in the payload are persisted on creation
    (previously silently dropped)."""
    repo = PropertyRepo(tmp_db)
    result = resolve_property(repo, {
        "external_alias": "with-amenities",
        "total_units": 4,
        "amenities": {"existing": ["pool", "gym"], "planned": ["dog park"]},
    })
    assert result.amenities.existing == ["pool", "gym"]
    assert result.amenities.planned == ["dog park"]


def test_resolve_property_id_with_conflicting_alias_raises(tmp_db):
    """Followup: caller-supplied external_alias that conflicts with the
    stored alias on a property_id-resolved row must raise (was silently
    ignored, masking caller bugs)."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(
        property_id="", external_alias="stored-alias", total_units=4,
    ))
    with pytest.raises(ValueError) as exc:
        resolve_property(repo, {
            "property_id": p.property_id,
            "external_alias": "different-alias",
        })
    assert hasattr(exc.value, "validation_problem")
    assert exc.value.validation_problem.error_type == "validation_error"
    assert any(
        fe.get("loc") == ["external_alias"]
        for fe in exc.value.validation_problem.field_errors
    )


def test_resolve_property_id_with_matching_alias_returns(tmp_db):
    """When the supplied external_alias matches the stored one, no error."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(
        property_id="", external_alias="ok-alias", total_units=4,
    ))
    result = resolve_property(repo, {
        "property_id": p.property_id,
        "external_alias": "ok-alias",
    })
    assert result.property_id == p.property_id


def test_resolve_property_id_with_alias_when_stored_alias_is_none(tmp_db):
    """When the row has no stored alias, a caller-supplied alias is silently
    accepted (no conflict to detect). Future ergonomics may want this to
    actually update the row, but that's out of scope here."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", external_alias=None, total_units=4))
    result = resolve_property(repo, {
        "property_id": p.property_id,
        "external_alias": "new-alias",
    })
    assert result.property_id == p.property_id


# --- resolve_floor_plan_by_dims ---------------------------------------------

def test_resolve_floor_plan_existing_match_returns(tmp_db):
    """Returns the existing FloorPlan when dims match exactly."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=4))
    fp = repo.create_floor_plan(FloorPlan(
        floor_plan_id="", property_id=p.property_id,
        name="existing-plan", sqft=850.0, bedrooms=2, bathrooms=1,
    ))
    result = resolve_floor_plan_by_dims(repo, p.property_id, 850.0, 2, 1)
    assert result.floor_plan_id == fp.floor_plan_id
    assert result.name == "existing-plan"


def test_resolve_floor_plan_no_match_mints_with_auto_name(tmp_db):
    """Mints a new FloorPlan with auto:<sqft>sf-<beds>x<baths> when no match."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=4))
    result = resolve_floor_plan_by_dims(repo, p.property_id, 850.0, 2, 1)
    assert result.floor_plan_id != ""
    assert result.name == "auto:850sf-2x1"


def test_resolve_floor_plan_integer_sqft_vs_float_naming(tmp_db):
    """Integer sqft (no .0 suffix) vs non-integer sqft in the name."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=4))
    # Integer sqft → should render as "750" not "750.0"
    int_result = resolve_floor_plan_by_dims(repo, p.property_id, 750.0, 1, 1)
    assert int_result.name == "auto:750sf-1x1"
    # Non-integer sqft → keeps decimal
    float_result = resolve_floor_plan_by_dims(repo, p.property_id, 750.5, 1, 1)
    assert float_result.name == "auto:750.5sf-1x1"


def test_resolve_floor_plan_explicit_name_overrides_auto_format(tmp_db):
    """Caller-supplied ``name`` is used instead of the auto:<sqft>sf-... format."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=4))
    result = resolve_floor_plan_by_dims(
        repo, p.property_id, 900.0, 2, 2, name="Two-Two"
    )
    assert result.name == "Two-Two"
    # Sanity: auto format would have been "auto:900sf-2x2"
    assert result.name != "auto:900sf-2x2"


def test_resolve_floor_plan_notes_and_alias_propagated(tmp_db):
    """Optional ``notes`` and ``external_alias`` kwargs are stored on the new row."""
    repo = PropertyRepo(tmp_db)
    p = repo.create(Property(property_id="", total_units=4))
    result = resolve_floor_plan_by_dims(
        repo, p.property_id, 800.0, 1, 1,
        notes="corner unit, extra windows",
        external_alias="ext-fp-001",
    )
    assert result.notes == "corner unit, extra windows"
    assert result.external_alias == "ext-fp-001"
