"""Canonical Pydantic schemas for plat-costmodel.

This submodule is structured to be extractable into a standalone
``plat-schemas`` package when a third consumer appears. Until then, all
canonical types live here and are re-exported at package level.
"""
from plat_costmodel.schemas.actuals import ActualOutcome
from plat_costmodel.schemas.errors import ValidationProblem, raise_problem
from plat_costmodel.schemas.estimate import (
    AmenityScopeEstimate,
    DeferredMaintenanceEstimate,
    ExteriorScopeEstimate,
    InteriorScopeEstimate,
    PricingSnapshot,
    ScopeEstimate,  # alias for InteriorScopeEstimate, kept for slice-A code
    ScopeEstimateUnion,
)
from plat_costmodel.schemas.property import (
    AmenityInventory,
    FloorPlan,
    Property,
)
from plat_costmodel.schemas.results import (
    OccupancyLiftResult,
    RentPremiumResult,
)
from plat_costmodel.schemas.scenario import (
    AmenityScenario,
    DeferredMaintenanceScenario,
    ExteriorScenario,
    InteriorScenario,
    ScenarioUnion,
)
from plat_costmodel.schemas.scope import (
    AmenityCohort,
    CohortUnion,
    DeferredMaintenanceCohort,
    ExteriorCohort,
    ProgramSchedule,
    ProgramType,
    ScopeRequest,
    UnitCohort,
)

__all__ = [
    "ActualOutcome",
    "AmenityCohort",
    "AmenityInventory",
    "AmenityScopeEstimate",
    "AmenityScenario",
    "CohortUnion",
    "DeferredMaintenanceCohort",
    "DeferredMaintenanceEstimate",
    "DeferredMaintenanceScenario",
    "ExteriorCohort",
    "ExteriorScopeEstimate",
    "ExteriorScenario",
    "FloorPlan",
    "InteriorScopeEstimate",
    "InteriorScenario",
    "OccupancyLiftResult",
    "PricingSnapshot",
    "ProgramSchedule",
    "ProgramType",
    "Property",
    "RentPremiumResult",
    "ScenarioUnion",
    "ScopeEstimate",
    "ScopeEstimateUnion",
    "ScopeRequest",
    "UnitCohort",
    "ValidationProblem",
    "raise_problem",
]
