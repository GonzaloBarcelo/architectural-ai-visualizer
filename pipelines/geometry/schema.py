"""Metric source-linked architecture v1. All deliverable geometry must be verified."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon

Point = tuple[float, float]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(Strict):
    page: int = Field(ge=1)
    primitive: int | None = None
    pdf_coordinates: list[Point]
    note: str
    status: Literal["verified", "inferred", "missing"]
    confidence: float = Field(ge=0, le=1)


class Entity(Strict):
    id: str
    floor_id: str
    evidence: Evidence


class Surface(Entity):
    polygon: list[Point] = Field(min_length=3)
    elevation: float
    thickness: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_polygon(self):
        p = Polygon(self.polygon)
        if not p.is_valid or p.area < 1e-6 or p.interiors:
            raise ValueError(f"{self.id}: invalid or degenerate polygon")
        return self


class Wall(Surface):
    height: float = Field(gt=0)


class Opening(Entity):
    kind: Literal["door", "window"]
    wall_id: str
    polygon: list[Point] = Field(min_length=3)
    sill: float = Field(ge=0)
    height: float = Field(gt=0)


class Room(Entity):
    name: str
    polygon: list[Point] = Field(min_length=3)


class Floor(Strict):
    id: str
    name: str
    elevation: float
    evidence: Evidence


class Transform(Strict):
    metres_per_point: float = Field(gt=0)
    origin_pdf: Point
    y_axis: Literal["up"] = "up"


class Measurement(Strict):
    id: str
    value_m: float = Field(gt=0)
    endpoints_pdf: tuple[Point, Point]
    evidence: Evidence


class Source(Strict):
    filename: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)


class Geometry(Strict):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    title: str
    synthetic: bool = False
    conceptual: bool = False
    units: Literal["m"] = "m"
    source: Source
    transform: Transform
    floors: list[Floor] = Field(min_length=1)
    walls: list[Wall] = Field(min_length=1)
    openings: list[Opening] = []
    rooms: list[Room] = []
    slabs: list[Surface] = Field(min_length=1)
    roofs: list[Surface] = []
    outdoor_areas: list[Surface] = []
    measurements: list[Measurement] = Field(min_length=1)
    missing_information: list[str] = []
    assumptions: list[str] = []

    @model_validator(mode="after")
    def consistency(self):
        entities = [
            *self.walls,
            *self.openings,
            *self.rooms,
            *self.slabs,
            *self.roofs,
            *self.outdoor_areas,
        ]
        ids = [x.id for x in entities] + [f.id for f in self.floors]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate architectural identifiers")
        floors = {f.id: f for f in self.floors}
        for item in entities:
            if item.floor_id not in floors:
                raise ValueError(f"{item.id}: unknown floor")
            p = Polygon(item.polygon)
            if not p.is_valid or p.area < 1e-6:
                raise ValueError(f"{item.id}: invalid polygon")
        walls = {w.id: w for w in self.walls}
        for op in self.openings:
            wall = walls.get(op.wall_id)
            if not wall or op.floor_id != wall.floor_id:
                raise ValueError(f"{op.id}: invalid host wall")
            if not Polygon(wall.polygon).buffer(0.002).covers(Polygon(op.polygon)):
                raise ValueError(f"{op.id}: opening outside host wall")
            if op.sill + op.height > wall.height + 1e-6:
                raise ValueError(f"{op.id}: opening exceeds wall height")
        for i, wall in enumerate(self.walls):
            if abs(wall.elevation - floors[wall.floor_id].elevation) > 1e-6:
                raise ValueError(f"{wall.id}: floor elevation mismatch")
            for other in self.walls[i + 1 :]:
                if (
                    wall.floor_id == other.floor_id
                    and Polygon(wall.polygon).intersection(Polygon(other.polygon)).area > 1e-5
                ):
                    raise ValueError(f"{wall.id}: overlapping wall {other.id}")
        for m in self.measurements:
            expected = math.dist(*m.endpoints_pdf) * self.transform.metres_per_point
            if abs(expected - m.value_m) > 0.002:
                raise ValueError(f"{m.id}: inconsistent verified scale")
        return self

    def require_verified(self):
        entities = [
            *self.floors,
            *self.walls,
            *self.openings,
            *self.rooms,
            *self.slabs,
            *self.roofs,
            *self.outdoor_areas,
            *self.measurements,
        ]
        allowed = {"verified", "inferred"} if self.conceptual and self.assumptions else {"verified"}
        unknown = [x.id for x in entities if x.evidence.status not in allowed]
        if self.missing_information or unknown:
            raise ValueError(
                f"Review required: {self.missing_information}; unverified entities: {unknown}"
            )
        return self
