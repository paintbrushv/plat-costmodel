"""SQLite repositories for canonical types."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from pydantic import TypeAdapter

from plat_costmodel.models import PropertyClass
from plat_costmodel.schemas import (
    AmenityInventory,
    CohortUnion,
    FloorPlan,
    Property,
    ScopeEstimateUnion,
)
from plat_costmodel.store.ids import new_ulid

# Module-level TypeAdapters for polymorphic deserialization. Allocating
# these per row is wasteful on bulk reads; cache once at import.
_COHORT_ADAPTER: TypeAdapter = TypeAdapter(CohortUnion)
_ESTIMATE_ADAPTER: TypeAdapter = TypeAdapter(ScopeEstimateUnion)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PropertyRepo:
    """Properties + their FloorPlans live together (parent-child)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- Property ----------------------------------------------------------

    def create(self, p: Property) -> Property:
        pid = p.property_id or new_ulid()
        amenities_json = p.amenities.model_dump_json()
        self.conn.execute(
            """INSERT INTO properties
               (property_id, external_alias, address, market, year_built,
                property_class, building_type, total_units, amenities_json,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid, p.external_alias, p.address, p.market, p.year_built,
                p.property_class.value if p.property_class else None,
                p.building_type, p.total_units, amenities_json, _now_iso(),
            ),
        )
        self.conn.commit()
        # Persist any inline floor plans.
        for fp in p.floor_plans:
            fp = fp.model_copy(update={"property_id": pid})
            self.create_floor_plan(fp)
        return self.get(pid)  # type: ignore[return-value]

    def get(self, property_id: str) -> Optional[Property]:
        row = self.conn.execute(
            "SELECT * FROM properties WHERE property_id = ?", (property_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_property(row)

    def get_by_alias(self, alias: str) -> Optional[Property]:
        row = self.conn.execute(
            "SELECT * FROM properties WHERE external_alias = ?", (alias,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_property(row)

    def _row_to_property(self, row: sqlite3.Row) -> Property:
        return Property(
            property_id=row["property_id"],
            external_alias=row["external_alias"],
            address=row["address"],
            market=row["market"],
            year_built=row["year_built"],
            property_class=PropertyClass(row["property_class"]) if row["property_class"] else None,
            building_type=row["building_type"],
            total_units=row["total_units"],
            amenities=AmenityInventory.model_validate_json(row["amenities_json"]),
            floor_plans=self.get_floor_plans(row["property_id"]),
        )

    # --- FloorPlan ---------------------------------------------------------

    def create_floor_plan(self, fp: FloorPlan) -> FloorPlan:
        fpid = fp.floor_plan_id or new_ulid()
        self.conn.execute(
            """INSERT INTO floor_plans
               (floor_plan_id, property_id, name, sqft, bedrooms, bathrooms,
                notes, external_alias)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fpid, fp.property_id, fp.name, fp.sqft, fp.bedrooms,
                fp.bathrooms, fp.notes, fp.external_alias,
            ),
        )
        self.conn.commit()
        return fp.model_copy(update={"floor_plan_id": fpid})

    def get_floor_plans(self, property_id: str) -> list[FloorPlan]:
        rows = self.conn.execute(
            "SELECT * FROM floor_plans WHERE property_id = ? ORDER BY name",
            (property_id,),
        ).fetchall()
        return [self._row_to_floor_plan(r) for r in rows]

    def get_floor_plan(self, floor_plan_id: str) -> Optional[FloorPlan]:
        row = self.conn.execute(
            "SELECT * FROM floor_plans WHERE floor_plan_id = ?", (floor_plan_id,)
        ).fetchone()
        return self._row_to_floor_plan(row) if row else None

    def get_floor_plan_by_alias(
        self, property_id: str, alias: str
    ) -> Optional[FloorPlan]:
        row = self.conn.execute(
            "SELECT * FROM floor_plans WHERE property_id = ? AND external_alias = ?",
            (property_id, alias),
        ).fetchone()
        return self._row_to_floor_plan(row) if row else None

    def find_floor_plan_by_dims(
        self, property_id: str, sqft: float, bedrooms: int, bathrooms: int
    ) -> Optional[FloorPlan]:
        """The (sqft, beds, baths) join key used by deal_projection."""
        row = self.conn.execute(
            """SELECT * FROM floor_plans
               WHERE property_id = ? AND sqft = ? AND bedrooms = ? AND bathrooms = ?
               LIMIT 1""",
            (property_id, sqft, bedrooms, bathrooms),
        ).fetchone()
        return self._row_to_floor_plan(row) if row else None

    @staticmethod
    def _row_to_floor_plan(row: sqlite3.Row) -> FloorPlan:
        return FloorPlan(
            floor_plan_id=row["floor_plan_id"],
            property_id=row["property_id"],
            name=row["name"],
            sqft=row["sqft"],
            bedrooms=row["bedrooms"],
            bathrooms=row["bathrooms"],
            notes=row["notes"],
            external_alias=row["external_alias"],
        )

    def get_history(self, property_id: str) -> list[dict]:
        """Return list of {scope_request, scope_estimate, actual_outcome}.

        For each scope_request against this property, attaches the latest
        scope_estimate (if any) and the latest actual_outcome (if any).
        Triple shape lets callers skip type-mux on the consumer side.
        """
        scope_repo = ScopeRepo(self.conn)
        est_repo = EstimateRepo(self.conn)
        actuals_repo = ActualsRepo(self.conn)
        triples = []
        for req in scope_repo.list_for_property(property_id):
            estimates = est_repo.list_for_request(req.scope_request_id)
            actuals = actuals_repo.list_for_request(req.scope_request_id)
            triples.append({
                "scope_request": req,
                "scope_estimate": estimates[-1] if estimates else None,
                "actual_outcome": actuals[-1] if actuals else None,
            })
        return triples


class SnapshotRepo:
    """PricingSnapshots dedupe by ``kb_version_hash``: same KB content
    → same snapshot_id. ``external_feeds`` is empty in v1 and reserved
    for slice C."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_or_create_for_kb_hash(
        self, kb_version_hash: str, external_feeds: Optional[dict] = None
    ) -> "PricingSnapshot":
        from plat_costmodel.schemas import PricingSnapshot
        existing = self.conn.execute(
            "SELECT * FROM pricing_snapshots WHERE kb_version_hash = ?",
            (kb_version_hash,),
        ).fetchone()
        if existing:
            return self._row(existing)
        sid = new_ulid()
        captured = _now_iso()
        feeds = json.dumps(external_feeds or {})
        self.conn.execute(
            """INSERT INTO pricing_snapshots
               (snapshot_id, captured_at, kb_version_hash, external_feeds_json)
               VALUES (?, ?, ?, ?)""",
            (sid, captured, kb_version_hash, feeds),
        )
        self.conn.commit()
        return PricingSnapshot(
            snapshot_id=sid,
            captured_at=datetime.fromisoformat(captured),
            kb_version_hash=kb_version_hash,
            external_feeds=external_feeds or {},
        )

    def get(self, snapshot_id: str) -> Optional["PricingSnapshot"]:
        row = self.conn.execute(
            "SELECT * FROM pricing_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> "PricingSnapshot":
        from plat_costmodel.schemas import PricingSnapshot
        return PricingSnapshot(
            snapshot_id=row["snapshot_id"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            kb_version_hash=row["kb_version_hash"],
            external_feeds=json.loads(row["external_feeds_json"]),
        )


class ScopeRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, req) -> "ScopeRequest":
        from plat_costmodel.schemas import ScopeRequest
        rid = req.scope_request_id or new_ulid()
        self.conn.execute(
            """INSERT INTO scope_requests
               (scope_request_id, property_id, program_type,
                cohort_json, schedule_json, requested_at, requested_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                rid, req.property_id, req.program_type.value,
                req.cohort.model_dump_json(),
                req.schedule.model_dump_json(),
                req.requested_at.isoformat(),
                req.requested_by,
            ),
        )
        self.conn.commit()
        return req.model_copy(update={"scope_request_id": rid})

    def get(self, scope_request_id: str) -> Optional["ScopeRequest"]:
        row = self.conn.execute(
            "SELECT * FROM scope_requests WHERE scope_request_id = ?",
            (scope_request_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_for_property(self, property_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM scope_requests WHERE property_id = ? ORDER BY requested_at",
            (property_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> "ScopeRequest":
        from plat_costmodel.schemas import (
            ProgramSchedule,
            ProgramType,
            ScopeRequest,
        )
        return ScopeRequest(
            scope_request_id=row["scope_request_id"],
            property_id=row["property_id"],
            program_type=ProgramType(row["program_type"]),
            cohort=_COHORT_ADAPTER.validate_json(row["cohort_json"]),
            schedule=ProgramSchedule.model_validate_json(row["schedule_json"]),
            requested_at=datetime.fromisoformat(row["requested_at"]),
            requested_by=row["requested_by"],
        )


class EstimateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, est):
        """Persist any ScopeEstimateUnion variant.

        Writes the full estimate as JSON in ``estimate_json``. Variant-specific
        fields (e.g. ``floor_plan_id`` on InteriorScopeEstimate) are also
        denormalized into dedicated columns when present, for query convenience.
        """
        eid = est.estimate_id or new_ulid()
        # floor_plan_id only exists on the interior variant.
        floor_plan_id = getattr(est, "floor_plan_id", None)
        # Stamp the minted id back onto the model before serializing so the
        # blob and the column agree.
        est_with_id = est.model_copy(update={"estimate_id": eid})
        self.conn.execute(
            """INSERT INTO scope_estimates
               (estimate_id, scope_request_id, property_id, floor_plan_id,
                pricing_snapshot_id, scope_type, estimate_json, estimated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid, est_with_id.scope_request_id, est_with_id.property_id,
                floor_plan_id, est_with_id.pricing_snapshot_id,
                est_with_id.scope_type,
                est_with_id.model_dump_json(),
                est_with_id.estimated_at.isoformat(),
            ),
        )
        self.conn.commit()
        return est_with_id

    def get(self, estimate_id: str):
        row = self.conn.execute(
            "SELECT * FROM scope_estimates WHERE estimate_id = ?",
            (estimate_id,),
        ).fetchone()
        return self._row(row) if row else None

    def list_for_property(self, property_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM scope_estimates WHERE property_id = ? ORDER BY estimated_at",
            (property_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def list_for_request(self, scope_request_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM scope_estimates WHERE scope_request_id = ? ORDER BY estimated_at",
            (scope_request_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def get_for_floor_plan(
        self, floor_plan_id: str, since: datetime | None = None
    ) -> list:
        """Interior-only by definition (floor_plan_id is null for the others).
        Used for per-floor-plan cost calibration over time."""
        sql = "SELECT * FROM scope_estimates WHERE floor_plan_id = ?"
        args: tuple = (floor_plan_id,)
        if since is not None:
            sql += " AND estimated_at >= ?"
            args = (floor_plan_id, since.isoformat())
        sql += " ORDER BY estimated_at"
        rows = self.conn.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row):
        return _ESTIMATE_ADAPTER.validate_json(row["estimate_json"])


class ActualsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, outcome) -> "ActualOutcome":
        from plat_costmodel.schemas import ActualOutcome
        aid = outcome.actual_id or new_ulid()
        self.conn.execute(
            """INSERT INTO actual_outcomes
               (actual_id, scope_request_id, property_id, line_items_json,
                total_actual, completed_at, source, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid, outcome.scope_request_id, outcome.property_id,
                json.dumps([li.model_dump(mode="json") for li in outcome.line_items]),
                outcome.total_actual, outcome.completed_at.isoformat(),
                outcome.source, outcome.notes,
            ),
        )
        self.conn.commit()
        return outcome.model_copy(update={"actual_id": aid})

    def get(self, actual_id: str) -> Optional["ActualOutcome"]:
        row = self.conn.execute(
            "SELECT * FROM actual_outcomes WHERE actual_id = ?", (actual_id,)
        ).fetchone()
        return self._row(row) if row else None

    def list_for_request(self, scope_request_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM actual_outcomes WHERE scope_request_id = ? ORDER BY completed_at",
            (scope_request_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> "ActualOutcome":
        from plat_costmodel.models import LineItem
        from plat_costmodel.schemas import ActualOutcome
        return ActualOutcome(
            actual_id=row["actual_id"],
            scope_request_id=row["scope_request_id"],
            property_id=row["property_id"],
            line_items=[LineItem.model_validate(d) for d in json.loads(row["line_items_json"])],
            total_actual=row["total_actual"],
            completed_at=datetime.fromisoformat(row["completed_at"]),
            source=row["source"],
            notes=row["notes"],
        )
