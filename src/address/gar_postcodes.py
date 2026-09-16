"""Офлайн-индекс домов ГАР. SDK Pullenti и Gar77 устанавливаются отдельно."""

import math
import re
from collections import defaultdict

from address.geocoding import normalize_address

MOSCOW_GUID = "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"
MAX_DISTANCE_METERS = 100
_NUMBER = r"[0-9]+[а-я]?(?:/[0-9]+[а-я]?)?"
_HOUSE = re.compile(rf"(?:дом )?({_NUMBER})(?: корпус ({_NUMBER}))?(?: строение ({_NUMBER}))?")


def street_key(text):
    # «улица Пятницкая» и «Пятницкая улица» — один ключ; тип улицы сохраняется.
    return tuple(sorted(normalize_address(text).split()))


def house_key(text):
    match = _HOUSE.fullmatch(normalize_address(text))
    return match.groups() if match else None


def distance_meters(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    value = (
        math.sin((b - a) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 12742000 * math.asin(min(1, math.sqrt(value)))


def build_index(path, *, wanted_streets):
    """Обход иерархии вместо дорогого разбора каждого текста; помещения не читаем."""
    from pullenti.address.AddressService import AddressService as service
    from pullenti.address.GarParam import GarParam

    service.initialize()
    service.set_gar_index_path(str(path.resolve()))

    def children(identifier, ignore_houses):
        result = service.get_children_objects(identifier, ignore_houses)
        if result is None:
            raise RuntimeError(f"ГАР: не удалось прочитать дочерние объекты {identifier}")
        return result

    roots = [item for item in children(None, True) if item.guid == MOSCOW_GUID]
    if len(roots) != 1:
        raise ValueError("В индексе ГАР не найден регион Москва")
    pending, seen, index = roots, set(), defaultdict(list)
    streets = 0
    while pending:
        parent = pending.pop()
        if parent.id0_ in seen or parent.expired:
            continue
        seen.add(parent.id0_)
        key = street_key(str(parent))
        is_street = parent.level.name == "STREET"
        wanted = is_street and key in wanted_streets
        for item in children(parent.id0_, not wanted):
            if item.expired or item.status.name != "OK":
                continue
            if item.level.name not in {"BUILDING", "ROOM", "CARPLACE", "PLOT"}:
                pending.append(item)
                continue
            if not wanted or item.level.name != "BUILDING" or not item.guid:
                continue
            attrs = item.attrs
            if attrs.plot_number or attrs.typ.name not in {"UNDEFINED", "HOUSE"}:
                continue
            if attrs.stroen_number and attrs.stroen_typ.name != "BUILDING":
                continue
            house = house_key(str(attrs))
            if house is None:
                continue
            gps = item.get_param_value(GarParam.GPSPOINT)
            postcode = item.get_param_value(GarParam.POSTINDEX)
            if not gps:
                continue
            try:
                lat, lon = map(float, gps.split())
            except (ValueError, AttributeError):
                continue
            if not (
                math.isfinite(lat)
                and math.isfinite(lon)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                continue
            index[key, house].append((item.guid, postcode, lat, lon))
        if wanted:
            streets += 1
            if streets % 500 == 0:
                print(f"ГАР: прочитано улиц {streets}", flush=True)
    return index, service.VERSION


def lookup(index, street, house, latitude, longitude):
    """Индекс только при одном совпавшем доме в радиусе 100 м. Не ближайший дом."""
    candidates = {
        row[0]: row
        for row in index.get((street_key(street), house_key(house)), [])
        if distance_meters(latitude, longitude, row[2], row[3]) <= MAX_DISTANCE_METERS
    }
    if len(candidates) != 1:
        return None
    guid, postcode, _, _ = next(iter(candidates.values()))
    if not isinstance(postcode, str) or not re.fullmatch(r"[0-9]{6}", postcode):
        return None
    return {"gar_guid": guid, "postal_code": postcode}
