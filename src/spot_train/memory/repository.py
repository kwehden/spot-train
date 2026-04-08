"""Repository interfaces for world-memory access."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from spot_train.memory.familiarity import FamiliarityAssessment, derive_familiarity_from_row
from spot_train.memory.schema import create_schema
from spot_train.models import (
    ApprovalProfile,
    Asset,
    AssetAlias,
    ConditionResult,
    EntityType,
    FamiliarityFactors,
    GraphRef,
    InspectionProfile,
    Observation,
    OperatorEvent,
    OutcomeCode,
    Place,
    PlaceAlias,
    ResolutionMode,
    Task,
    TaskStatus,
    TaskStep,
)

ModelT = TypeVar("ModelT")

_JSON_FIELDS: dict[type[Any], set[str]] = {
    Place: {"tags_json"},
    GraphRef: {"relocalization_hint_json"},
    Asset: {"tags_json"},
    InspectionProfile: {
        "required_evidence_json",
        "conditions_json",
        "capture_plan_json",
    },
    TaskStep: {"inputs_json", "outputs_json"},
    Observation: {"structured_data_json"},
    ConditionResult: {"evidence_ids_json"},
    OperatorEvent: {"details_json"},
}


class WorldRepository:
    """SQLite-backed repository for the MVP world model and task history."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON;")

    @classmethod
    def connect(
        cls,
        path: str | Path = ":memory:",
        *,
        initialize: bool = False,
    ) -> "WorldRepository":
        connection = sqlite3.connect(str(path), check_same_thread=False)
        repository = cls(connection)
        if initialize:
            create_schema(connection)
        return repository

    def close(self) -> None:
        self.connection.close()

    def create_place(self, place: Place) -> Place:
        payload = _model_to_record(place)
        self._insert(
            "places",
            payload,
        )
        return place

    def get_place(self, place_id: str) -> Place | None:
        row = self.connection.execute(
            "SELECT * FROM places WHERE place_id = ?",
            (place_id,),
        ).fetchone()
        return _row_to_model(Place, row)

    def list_places(self, *, active_only: bool = False) -> list[Place]:
        query = "SELECT * FROM places"
        params: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY canonical_name ASC"
        rows = self.connection.execute(query, params).fetchall()
        return [_row_to_model(Place, row) for row in rows]

    def create_place_alias(self, alias: PlaceAlias) -> PlaceAlias:
        self._insert("place_aliases", _model_to_record(alias))
        return alias

    def list_place_aliases(self, place_id: str) -> list[PlaceAlias]:
        rows = self.connection.execute(
            "SELECT * FROM place_aliases WHERE place_id = ? ORDER BY alias ASC",
            (place_id,),
        ).fetchall()
        return [_row_to_model(PlaceAlias, row) for row in rows]

    def get_place_by_alias(self, alias: str) -> Place | None:
        row = self.connection.execute(
            """
            SELECT p.*
            FROM places AS p
            JOIN place_aliases AS pa ON pa.place_id = p.place_id
            WHERE lower(pa.alias) = lower(?)
            LIMIT 1
            """,
            (alias,),
        ).fetchone()
        return _row_to_model(Place, row)

    def create_graph_ref(self, graph_ref: GraphRef) -> GraphRef:
        self._insert("graph_refs", _model_to_record(graph_ref))
        return graph_ref

    def list_graph_refs(self, place_id: str, *, active_only: bool = True) -> list[GraphRef]:
        query = "SELECT * FROM graph_refs WHERE place_id = ?"
        params: list[Any] = [place_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY created_at ASC"
        rows = self.connection.execute(query, tuple(params)).fetchall()
        return [_row_to_model(GraphRef, row) for row in rows]

    def create_asset(self, asset: Asset) -> Asset:
        self._insert("assets", _model_to_record(asset))
        return asset

    def get_asset(self, asset_id: str) -> Asset | None:
        row = self.connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        return _row_to_model(Asset, row)

    def list_assets(self, *, place_id: str | None = None) -> list[Asset]:
        query = "SELECT * FROM assets"
        params: tuple[Any, ...] = ()
        if place_id is not None:
            query += " WHERE place_id = ?"
            params = (place_id,)
        query += " ORDER BY canonical_name ASC"
        rows = self.connection.execute(query, params).fetchall()
        return [_row_to_model(Asset, row) for row in rows]

    def create_asset_alias(self, alias: AssetAlias) -> AssetAlias:
        self._insert("asset_aliases", _model_to_record(alias))
        return alias

    def list_asset_aliases(self, asset_id: str) -> list[AssetAlias]:
        rows = self.connection.execute(
            "SELECT * FROM asset_aliases WHERE asset_id = ? ORDER BY alias ASC",
            (asset_id,),
        ).fetchall()
        return [_row_to_model(AssetAlias, row) for row in rows]

    def get_asset_by_alias(self, alias: str) -> Asset | None:
        row = self.connection.execute(
            """
            SELECT a.*
            FROM assets AS a
            JOIN asset_aliases AS aa ON aa.asset_id = a.asset_id
            WHERE lower(aa.alias) = lower(?)
            LIMIT 1
            """,
            (alias,),
        ).fetchone()
        return _row_to_model(Asset, row)

    def create_approval_profile(self, profile: ApprovalProfile) -> ApprovalProfile:
        self._insert("approval_profiles", _model_to_record(profile))
        return profile

    def get_approval_profile(self, approval_profile_id: str) -> ApprovalProfile | None:
        row = self.connection.execute(
            "SELECT * FROM approval_profiles WHERE approval_profile_id = ?",
            (approval_profile_id,),
        ).fetchone()
        return _row_to_model(ApprovalProfile, row)

    def create_inspection_profile(self, profile: InspectionProfile) -> InspectionProfile:
        self._insert("inspection_profiles", _model_to_record(profile))
        return profile

    def get_inspection_profile(self, profile_id: str) -> InspectionProfile | None:
        row = self.connection.execute(
            "SELECT * FROM inspection_profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return _row_to_model(InspectionProfile, row)

    def create_task(self, task: Task) -> Task:
        self._insert("tasks", _model_to_record(task))
        return task

    def get_task(self, task_id: str) -> Task | None:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return _row_to_model(Task, row)

    def update_task(self, task: Task) -> Task:
        payload = _model_to_record(task)
        task_id = payload.pop("task_id")
        assignments = ", ".join(f"{key} = ?" for key in payload)
        values = tuple(payload.values()) + (task_id,)
        with self.connection:
            self.connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                values,
            )
        return task

    def update_task_status(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        outcome_code: OutcomeCode | None = None,
        result_summary: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        resolved_target_type: EntityType | None = None,
        resolved_target_id: str | None = None,
        resolution_mode: ResolutionMode | None = None,
        resolution_confidence: float | None = None,
    ) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task_id: {task_id}")
        task.status = status
        if outcome_code is not None:
            task.outcome_code = outcome_code
        if result_summary is not None:
            task.result_summary = result_summary
        if started_at is not None:
            task.started_at = started_at
        if ended_at is not None:
            task.ended_at = ended_at
        if resolved_target_type is not None:
            task.resolved_target_type = resolved_target_type
        if resolved_target_id is not None:
            task.resolved_target_id = resolved_target_id
        if resolution_mode is not None:
            task.resolution_mode = resolution_mode
        if resolution_confidence is not None:
            task.resolution_confidence = resolution_confidence
        return self.update_task(task)

    def append_task_step(self, step: TaskStep) -> TaskStep:
        sequence_no = self.connection.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM task_steps WHERE task_id = ?",
            (step.task_id,),
        ).fetchone()[0]
        stored_step = step.model_copy(update={"sequence_no": int(sequence_no)})
        self._insert("task_steps", _model_to_record(stored_step))
        return stored_step

    def list_task_steps(self, task_id: str) -> list[TaskStep]:
        rows = self.connection.execute(
            "SELECT * FROM task_steps WHERE task_id = ? ORDER BY sequence_no ASC",
            (task_id,),
        ).fetchall()
        return [_row_to_model(TaskStep, row) for row in rows]

    def create_observation(self, observation: Observation) -> Observation:
        self._insert("observations", _model_to_record(observation))
        return observation

    def list_observations(
        self,
        task_id: str,
        *,
        place_id: str | None = None,
        asset_id: str | None = None,
    ) -> list[Observation]:
        query = "SELECT * FROM observations WHERE task_id = ?"
        params: list[Any] = [task_id]
        if place_id is not None:
            query += " AND place_id = ?"
            params.append(place_id)
        if asset_id is not None:
            query += " AND asset_id = ?"
            params.append(asset_id)
        query += " ORDER BY captured_at ASC"
        rows = self.connection.execute(query, tuple(params)).fetchall()
        return [_row_to_model(Observation, row) for row in rows]

    def create_condition_result(self, result: ConditionResult) -> ConditionResult:
        self._insert("condition_results", _model_to_record(result))
        return result

    def list_condition_results(self, task_id: str) -> list[ConditionResult]:
        rows = self.connection.execute(
            "SELECT * FROM condition_results WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [_row_to_model(ConditionResult, row) for row in rows]

    def upsert_familiarity_factors(self, factors: FamiliarityFactors) -> FamiliarityFactors:
        payload = _model_to_record(factors)
        columns = ", ".join(payload)
        placeholders = ", ".join("?" for _ in payload)
        assignments = ", ".join(
            f"{column} = excluded.{column}" for column in payload if column != "place_id"
        )
        self.connection.execute(
            f"""
            INSERT INTO familiarity_factors ({columns})
            VALUES ({placeholders})
            ON CONFLICT(place_id) DO UPDATE SET {assignments}
            """,
            tuple(payload.values()),
        )
        stored = self.get_familiarity_factors(factors.place_id)
        if stored is None:
            raise RuntimeError("Failed to upsert familiarity factors")
        return stored

    def get_familiarity_factors(self, place_id: str) -> FamiliarityFactors | None:
        row = self.connection.execute(
            "SELECT * FROM familiarity_factors WHERE place_id = ?",
            (place_id,),
        ).fetchone()
        return _row_to_model(FamiliarityFactors, row)

    def get_derived_familiarity(self, place_id: str) -> FamiliarityAssessment | None:
        row = self.connection.execute(
            "SELECT * FROM familiarity_factors WHERE place_id = ?",
            (place_id,),
        ).fetchone()
        if row is None:
            return None
        return derive_familiarity_from_row(row)

    def create_operator_event(self, event: OperatorEvent) -> OperatorEvent:
        self._insert("operator_events", _model_to_record(event))
        return event

    def list_operator_events(self, *, task_id: str | None = None) -> list[OperatorEvent]:
        query = "SELECT * FROM operator_events"
        params: tuple[Any, ...] = ()
        if task_id is not None:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY created_at ASC"
        rows = self.connection.execute(query, params).fetchall()
        return [_row_to_model(OperatorEvent, row) for row in rows]

    def seed_minimal_lab_world(self) -> dict[str, Sequence[Any]]:
        optics_bench = self.create_place(
            Place(
                place_id="plc_optics_bench",
                canonical_name="Optics Bench",
                zone="Lab A",
                tags_json=["inspection", "bench"],
                notes="Primary optics workstation.",
            )
        )
        charging_station = self.create_place(
            Place(
                place_id="plc_charging_station",
                canonical_name="Charging Station",
                zone="Lab A",
                tags_json=["dock", "power"],
                notes="Robot dock and charger.",
            )
        )
        self.create_place_alias(
            PlaceAlias(
                alias_id="als_optics_bench",
                place_id=optics_bench.place_id,
                alias="optics bench",
            )
        )
        self.create_place_alias(
            PlaceAlias(
                alias_id="als_bench_alpha",
                place_id=optics_bench.place_id,
                alias="bench alpha",
                alias_type="imported",
                confidence_hint=0.91,
            )
        )
        self.create_place_alias(
            PlaceAlias(
                alias_id="als_charging_station",
                place_id=charging_station.place_id,
                alias="charging station",
            )
        )
        charger = self.create_asset(
            Asset(
                asset_id="ast_spot_dock",
                place_id=charging_station.place_id,
                canonical_name="Spot Dock",
                asset_type="charger",
                tags_json=["dock", "spot"],
            )
        )
        microscope = self.create_asset(
            Asset(
                asset_id="ast_optics_scope",
                place_id=optics_bench.place_id,
                canonical_name="Alignment Microscope",
                asset_type="instrument",
                tags_json=["optics", "inspection"],
            )
        )
        self.create_asset_alias(
            AssetAlias(
                alias_id="als_spot_dock",
                asset_id=charger.asset_id,
                alias="spot dock",
            )
        )
        self.create_asset_alias(
            AssetAlias(
                alias_id="als_alignment_scope",
                asset_id=microscope.asset_id,
                alias="alignment scope",
            )
        )
        return {
            "places": [optics_bench, charging_station],
            "assets": [charger, microscope],
        }

    def _insert(self, table: str, payload: dict[str, Any]) -> None:
        columns = ", ".join(payload)
        placeholders = ", ".join("?" for _ in payload)
        with self.connection:
            self.connection.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                tuple(payload.values()),
            )


def _model_to_record(model: Any) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    for field_name in _JSON_FIELDS.get(type(model), set()):
        value = payload.get(field_name)
        if value is not None:
            payload[field_name] = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return payload


def _row_to_model(model_type: type[ModelT], row: sqlite3.Row | None) -> ModelT | None:
    if row is None:
        return None
    payload = dict(row)
    for field_name in _JSON_FIELDS.get(model_type, set()):
        value = payload.get(field_name)
        if value is not None:
            payload[field_name] = json.loads(value)
    return model_type.model_validate(payload)


__all__ = ["WorldRepository"]
