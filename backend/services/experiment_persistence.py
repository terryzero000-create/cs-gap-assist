from backend.models.schemas import ExperimentPlan, ExperimentSuggestResponse
from backend.repositories.sqlite_store import SQLiteStore


def persist_trusted_experiments(
    store: SQLiteStore,
    response: ExperimentSuggestResponse,
) -> tuple[list[ExperimentPlan], list[str]]:
    """Persist only trusted suggestions and return safe persistence warnings."""
    if response.evidence_status not in {"verified", "local_only"}:
        return [], []

    persisted: list[ExperimentPlan] = []
    warnings: list[str] = []
    for experiment in response.experiments:
        if experiment.trust_status not in {"verified", "local_only"}:
            continue
        try:
            persisted.append(store.save_experiment(experiment))
        except ValueError:
            warnings.append(
                f"Experiment {experiment.experiment_id} was not persisted because its support evidence could not be verified."
            )
    return persisted, warnings
