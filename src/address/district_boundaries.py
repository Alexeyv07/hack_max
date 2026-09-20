"""Разбор OSM admin_level=8 границ Москвы и point-in-polygon без GIS-зависимостей."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DISTRICT_PREFIXES = (
    "внутригородская территория города федерального значения ",
    "внутригородское муниципальное образование ",
    "муниципальный округ ",
    "район ",
)


def clean_district_name(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(value.split()).strip()
    folded = text.casefold().replace("ё", "е")
    for prefix in _DISTRICT_PREFIXES:
        if folded.startswith(prefix):
            text = text[len(prefix) :].strip(" -—")
            folded = text.casefold().replace("ё", "е")
            break
    if not text or folded in {"москва", "moscow", "город москва", "москва город"}:
        return None
    return text


@dataclass(frozen=True, slots=True)
class DistrictBoundary:
    name: str
    outer_rings: tuple[tuple[tuple[float, float], ...], ...]
    inner_rings: tuple[tuple[tuple[float, float], ...], ...]
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def contains(self, latitude: float, longitude: float) -> bool:
        if not (self.min_lat <= latitude <= self.max_lat):
            return False
        if not (self.min_lon <= longitude <= self.max_lon):
            return False
        point = (longitude, latitude)
        if not any(_point_in_ring(point, ring) for ring in self.outer_rings):
            return False
        return not any(_point_in_ring(point, ring) for ring in self.inner_rings)


def _point_in_ring(point: tuple[float, float], ring: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting. Координаты в порядке (lon, lat)."""
    x, y = point
    inside = False
    if len(ring) < 4:
        return False
    previous_x, previous_y = ring[-1]
    for current_x, current_y in ring:
        # Точка на ребре считается внутри, чтобы дома на границе не терялись.
        cross = (current_x - previous_x) * (y - previous_y) - (current_y - previous_y) * (
            x - previous_x
        )
        if (
            abs(cross) < 1e-12
            and min(previous_x, current_x) <= x <= max(previous_x, current_x)
            and min(previous_y, current_y) <= y <= max(previous_y, current_y)
        ):
            return True
        if (current_y > y) != (previous_y > y):
            border_x = previous_x + (y - previous_y) * (current_x - previous_x) / (
                current_y - previous_y
            )
            if x < border_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _join_way_nodes(ways: list[list[int]]) -> list[list[int]]:
    """Склеить relation ways в замкнутые кольца независимо от их ориентации/порядка."""
    pending = [list(nodes) for nodes in ways if len(nodes) >= 2]
    rings: list[list[int]] = []
    while pending:
        ring = pending.pop()
        while ring[0] != ring[-1]:
            match_index = None
            merged: list[int] | None = None
            for index, segment in enumerate(pending):
                if segment[0] == ring[-1]:
                    merged = ring + segment[1:]
                elif segment[-1] == ring[-1]:
                    merged = ring + list(reversed(segment[:-1]))
                elif segment[-1] == ring[0]:
                    merged = segment[:-1] + ring
                elif segment[0] == ring[0]:
                    merged = list(reversed(segment[1:])) + ring
                else:
                    continue
                match_index = index
                break
            if match_index is None or merged is None:
                # Неполная relation/выгрузка. Не создаём ложную границу.
                ring = []
                break
            pending.pop(match_index)
            ring = merged
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def load_overpass_boundaries(path: Path) -> list[DistrictBoundary]:
    """Прочитать relation admin_level=8 + рекурсивные ways/nodes из Overpass JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("remark"):
        raise ValueError(f"Overpass вернул неполный ответ: {payload['remark']}")
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("Файл границ не содержит elements")

    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, list[int]] = {}
    relations: list[dict[str, Any]] = []
    for element in elements:
        kind = element.get("type")
        if kind == "node":
            nodes[int(element["id"])] = (float(element["lon"]), float(element["lat"]))
        elif kind == "way":
            ways[int(element["id"])] = [int(node_id) for node_id in element.get("nodes", [])]
        elif kind == "relation":
            tags = element.get("tags") or {}
            if tags.get("boundary") == "administrative" and tags.get("admin_level") == "8":
                relations.append(element)

    result: list[DistrictBoundary] = []
    for relation in relations:
        name = clean_district_name((relation.get("tags") or {}).get("name"))
        if not name:
            continue
        outer_ways: list[list[int]] = []
        inner_ways: list[list[int]] = []
        for member in relation.get("members", []):
            if member.get("type") != "way":
                continue
            nodes_for_way = ways.get(int(member.get("ref", 0)))
            if not nodes_for_way:
                continue
            if member.get("role") == "inner":
                inner_ways.append(nodes_for_way)
            elif member.get("role") in {"outer", ""}:
                outer_ways.append(nodes_for_way)

        def coordinates(rings: list[list[int]]) -> list[tuple[tuple[float, float], ...]]:
            converted = []
            for ring in _join_way_nodes(rings):
                try:
                    converted.append(tuple(nodes[node_id] for node_id in ring))
                except KeyError:
                    continue
            return converted

        outer = coordinates(outer_ways)
        if not outer:
            continue
        inner = coordinates(inner_ways)
        all_points = [point for ring in outer for point in ring]
        lons = [point[0] for point in all_points]
        lats = [point[1] for point in all_points]
        result.append(
            DistrictBoundary(
                name=name,
                outer_rings=tuple(outer),
                inner_rings=tuple(inner),
                min_lon=min(lons),
                min_lat=min(lats),
                max_lon=max(lons),
                max_lat=max(lats),
            )
        )
    if not result:
        raise ValueError("Не удалось собрать ни одной admin_level=8 границы")
    return sorted(result, key=lambda item: item.name.casefold())


def resolve_district(
    boundaries: list[DistrictBoundary], latitude: float, longitude: float
) -> str | None:
    for boundary in boundaries:
        if boundary.contains(latitude, longitude):
            return boundary.name
    return None
