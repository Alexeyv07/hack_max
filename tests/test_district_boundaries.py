import json
from pathlib import Path

from address.district_boundaries import load_overpass_boundaries, resolve_district


def _snapshot(path: Path) -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 55.82, "lon": 37.64},
            {"type": "node", "id": 2, "lat": 55.82, "lon": 37.68},
            {"type": "node", "id": 3, "lat": 55.85, "lon": 37.68},
            {"type": "node", "id": 4, "lat": 55.85, "lon": 37.64},
            # Нарочно не в геометрическом порядке и с разной ориентацией.
            {"type": "way", "id": 12, "nodes": [3, 2]},
            {"type": "way", "id": 10, "nodes": [1, 2]},
            {"type": "way", "id": 13, "nodes": [4, 1]},
            {"type": "way", "id": 11, "nodes": [3, 4]},
            {
                "type": "relation",
                "id": 100,
                "members": [
                    {"type": "way", "ref": 12, "role": "outer"},
                    {"type": "way", "ref": 10, "role": "outer"},
                    {"type": "way", "ref": 13, "role": "outer"},
                    {"type": "way", "ref": 11, "role": "outer"},
                ],
                "tags": {
                    "boundary": "administrative",
                    "admin_level": "8",
                    "name": "район Ростокино",
                },
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_admin_level_8_boundary_resolves_rostokino(tmp_path: Path) -> None:
    source = tmp_path / "districts.json"
    _snapshot(source)
    boundaries = load_overpass_boundaries(source)
    assert [item.name for item in boundaries] == ["Ростокино"]
    assert resolve_district(boundaries, 55.835, 37.66) == "Ростокино"
    assert resolve_district(boundaries, 55.90, 37.66) is None
