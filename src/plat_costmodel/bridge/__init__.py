"""Bridge package — translates between plat-costmodel and external schemas."""
from plat_costmodel.bridge.deal_projection import (
    CohortProjection,
    DealProjection,
    project_deal,
    project_deal_to_scope_requests,
)
from plat_costmodel.bridge.uw_projection import (
    BridgeResult,
    build_renovation_program_input,
    prepare_renovation_program,
    project_estimate_to_renovation_program,
    validate_against_roi,
)

__all__ = [
    "BridgeResult",
    "CohortProjection",
    "DealProjection",
    "build_renovation_program_input",
    "prepare_renovation_program",
    "project_deal",
    "project_deal_to_scope_requests",
    "project_estimate_to_renovation_program",
    "validate_against_roi",
]
