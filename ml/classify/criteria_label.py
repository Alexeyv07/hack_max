"""Разметка importance по продуктовым критериям «Касаетсяменя».

Порядок: признаки cat.1 → cat.2 → иначе cat.3.
disaster_flag — отдельно (городская ЧС), не синоним importance==1.

Неоднозначные тексты без контекста → LabelDecision.skip=True
(не кладём в train как «золотую» разметку).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

_PAST_DONE = re.compile(
    r"(?i)\b("
    r"вчера|потушен\w*|потушили|ликвидирован\w*|ликвидац\w*|"
    r"полностью\s+потушен\w*|угроз\w*\s+нет|ограничений\s+нет|"
    r"заверш[её]нн?\w*\s+(происшеств|мероприят|учени)|"
    r"отч[её]т\s+о\s+вчерашн|учения\s+прошли|прошли\s+учения|"
    r"истори\w+\s+информац|давно\s+потуш|"
    r"во\s+время\s+тушен|тушени\w*\s+пожара|обнаружили\s+во\s+время|"
    r"проливка\s+и\s+разборк"
    r")\b"
)

_EDU_SAFETY = re.compile(
    r"(?i)спички\s+детям|пожарная\s+безопасность\s+для|"
    r"что\s+же\s+должен\s+знать\s+каждый|"
    r"правил\w*\s+(безопасности|поведения\s+при\s+пожаре)|"
    r"памятк\w*\s+о\s+пожар|урок\w*\s+безопасности|"
    r"расскажи\s+детям|профилактик\w*\s+пожарн"
)

_NEGATION_OR_DRILL = re.compile(
    r"(?i)\b("
    r"учебн\w+\s+(проверк|эвакуац|тревог)|"
    r"проверка\s+сирен|"
    r"это\s+не\s+пожар|не\s+горит|ложн\w+\s+вызов|"
    r"мет\w+|шутк\w+|мем\b"
    r")\b"
)

# Контекст, где слово «пожар» / «эвакуация» не означает срочность
_FIRE_NON_EVENT = re.compile(
    r"(?i)пожарно[- ]?спасательн|пожарн\w*\s+(спорт|учени|соревнован|чемпионат|"
    r"центр|коллектив|дружин)|"
    r"урок\w*\s+безопасност|профилактическ\w*\s+мероприя|"
    r"памятк\w*\s+по\s+пожар|правил\w*\s+пожар|"
    r"день\s+пожарн|история\s+пожар"
)

_VIOLENCE_NON_EVENT = re.compile(
    r"(?i)назнач\w*\s+условн|приговор|возбужден\w*\s+уголовн|"
    r"расследован|статья\s+\d+\s+ук|суд\s+в\s+"
)

_CAT1 = [
    # огонь / дым (актуально)
    (re.compile(r"(?i)горит\b|открыт\w*\s+горен|полыха|возгоран"), "fire_active"),
    (
        re.compile(r"(?i)пожар\w*\s+в\s+(квартир|подъезд|подвал|доме|дом\b|секци|рынк|здани|жк)"),
        "fire_place",
    ),
    (
        re.compile(
            r"(?i)(?<!-)пожар(?!ил|но)(?:а|е|у|ом|ы|ов)?\b.{0,40}"
            r"(квартир|подъезд|подвал|дом|рынк|здани|жк|вспых|тушат|полыха|возгоран|задым|"
            r"эвакуир|пострад|погиб)|"
            r"(вспых|возгоран|тушат|полыха|задым).{0,30}пожар(?!ил|но)"
        ),
        "fire_word",
    ),
    (
        re.compile(r"(?i)задымлен|дым\s+в\s+(подъезд|квартир|подвал)|сильный\s+дым|столб\s+дыма"),
        "smoke",
    ),
    # газ / электричество
    (re.compile(r"(?i)запах\w*\s+газ|утечк\w*\s+газ|пахнет\s+газом"), "gas"),
    (re.compile(r"(?i)искрит|дымит\w*\s+электрощит|электрощит\s+дымит"), "electrical"),
    (
        re.compile(
            r"(?i)оборванн?\w*.{0,25}(провод|кабель).{0,25}(лежит|висит|на\s+(земл|дорожк|проход))|"
            r"(провод|кабель)\s+на\s+(земл|дорожк|проход)"
        ),
        "wire",
    ),
    # насилие / угроза жизни
    (
        re.compile(
            r"(?i)(угрожает\w*\s+нож|размахивает\s+нож|человек\w*\s+с\s+ножом|"
            r"с\s+ножом\s+угрож)"
        ),
        "knife",
    ),
    (
        re.compile(r"(?i)нападен\w*\s+на\s+(люд|человек|прохож)|избивают|насильственн\w*\s+проник"),
        "violence",
    ),
    (re.compile(r"(?i)взламывают\s+дверь|взлом\s+квартир"), "break_in"),
    (
        re.compile(
            r"(?i)(нужна\s+скорая|вызовите\s+скорую|экстренн\w*\s+помощ|"
            r"человек\w*\s+без\s+сознания|без\s+сознания.{0,30}(помощ|скор))"
        ),
        "medical",
    ),
    (
        re.compile(
            r"(?i)застрял\w*\s+в\s+лифте|в\s+лифте\s+застрял|"
            r"лифте\s+на\s+.{0,40}застрял|люди\s+в\s+лифте|в\s+лифте\s+.{0,40}люд"
        ),
        "elevator_trap",
    ),
    (
        re.compile(
            r"(?i)заперт\w*\s+в\s+(опасн|горящ|задымл|квартир|подъезд|лифт)|"
            r"не\s+может\s+выбраться"
        ),
        "trapped",
    ),
    (
        re.compile(r"(?i)пропал\w*\s+(маленьк\w*\s+)?(реб[её]нок|малыш)|поиск\s+реб[её]нк"),
        "missing_child",
    ),
    # затопление активное
    (
        re.compile(
            r"(?i)заливает|затопляет|вода\s+поступает\s+в\s+квартир|"
            r"прорвало\s+стояк|прорвало\s+трубу.*залив|стремительн\w*\s+поступ"
        ),
        "flood_active",
    ),
    # конструкции / животные / эвакуация
    (
        re.compile(r"(?i)падают?\s+(элемент|штукатур|облицовк|кирпич)|сыпется\s+с\s+фасад"),
        "falling",
    ),
    (re.compile(r"(?i)открыт\w*\s+(колодец|люк).*без\s+огражд|люк\s+без\s+крышк"), "manhole"),
    (
        re.compile(r"(?i)собак\w*\s+(нападает|бросается|атакует)|бросается\s+на\s+(людей|детей)"),
        "dog_attack",
    ),
    (
        re.compile(
            r"(?i)объявлен\w*\s+(немедленн\w*\s+)?эвакуац|срочн\w*\s+эвакуац|"
            r"эвакуация\s+из-за|организован\w*\s+эвакуац|"
            r"(?<!отменен\s)(?<!отменён\s)(?<!снят\s)режим\s+«?ракетн"
        ),
        "evac",
    ),
]

_CAT1_NEED_ACTIVE = {"fire_word", "fire_place", "smoke", "fire_active"}

_CAT2 = [
    (
        re.compile(
            r"(?i)отключ\w*.{0,40}(вод|гвс|хвс|горяч|холодн|свет|электрич|газ|отоплен)|"
            r"не\s+будет\s+(воды|газа|света|электричеств|гвс)|"
            r"без\s+(воды|света|газа|отопления|горячей\s+воды)|"
            r"опрессовк|гидравлическ\w*\s+испытан|"
            r"график\s+отключен|планов\w*\s+(отключен|работ\w*\s+на\s+сет)|"
            r"снизит\w*\s+давлен|черн\w*\s+вод|отопительн\w*\s+сезон\s+заверш"
        ),
        "outage",
    ),
    (re.compile(r"(?i)восстановлен\w*\s+(водоснаб|подач\w*\s+воды|горяч|электроснаб)"), "restored"),
    (
        re.compile(
            r"(?i)лифт\s+не\s+работает|не\s+работает\s+лифт|сломан\s+лифт|"
            r"лифт\s+сломан|кабина\s+пуста"
        ),
        "elevator_broken",
    ),
    (re.compile(r"(?i)домофон|замок\s+(входной|общей)|входная\s+дверь\s+не\s+закрыв"), "access"),
    (re.compile(r"(?i)освещен\w*\s+подъезд|свет\s+в\s+подъезд\w*\s+не"), "hallway_light"),
    (re.compile(r"(?i)протечк(?!.*залив)|капает\s+с\s+потолк|небольшая\s+течь"), "small_leak"),
    (re.compile(r"(?i)канализац\w*\s+не\s+работа|засор\s+канализац|санузл\w*\s+нельзя"), "sewage"),
    (
        re.compile(
            r"(?i)проверк\w*\s+(оборудован|газов|счётчик)|замена\s+стояк|"
            r"требуется\s+доступ|газовщик|отсечн\w*\s+кран|обеспечить\s+доступ"
        ),
        "access_needed",
    ),
    (
        re.compile(
            r"(?i)перекрыт\w*\s+(въезд|проезд|улиц|движен|дорог)|"
            r"ремонт\s+дорог|закроют\s+движен|не\s+парковать|уберите\s+машин|"
            r"трактор.{0,40}(снег|снен|уборк)|очистка\s+снега"
        ),
        "road_access",
    ),
    (re.compile(r"(?i)маршрут\s+автобус|остановк\w*\s+перенес|измен[её]н\w*\s+маршрут"), "transit"),
    (re.compile(r"(?i)обработк\w*\s+подъезд|дератизац|дезинсекц"), "treatment"),
    (re.compile(r"(?i)переполнен\w*\s+контейнер|вывоз\s+мусор|не\s+вывозят\s+мусор"), "trash"),
    (
        re.compile(
            r"(?i)собрани\w*\s+собственник|общ\w*\s+собрани|голосовани\w*\s+по\s+(управлен|дому)|"
            r"осс\b"
        ),
        "meeting",
    ),
    (
        re.compile(
            r"(?i)опасн\w*\s+погод|штормов\w*\s+предупрежд|экстренн\w*\s+предупрежд|"
            r"ожидаются?\s+(сильный\s+ветер|ливн|гроза)|порывы\s+ветра"
        ),
        "weather_warn",
    ),
    (
        re.compile(
            r"(?i)учебная\s+проверка\s+сирен|планов\w*\s+проверк|"
            r"перекрыли.*из-за\s+ремонт"
        ),
        "planned_proc",
    ),
]

_CAT3 = [
    (re.compile(r"(?i)пропал\w*\s+(кот|кошк|п[её]с|собак)|нашл\w*\s+(кот|кошк|собак)"), "pet"),
    (re.compile(r"(?i)потерял\w*\s+(ключ|кошел|документ)|нашл\w*\s+(ключ|кошел)"), "lost_item"),
    (re.compile(r"(?i)прода[мю]|отдам|ищу\s+мастер|одолжить|сдам\s+квартир"), "marketplace"),
    (
        re.compile(
            r"(?i)с\s+дн[её]м\s+рожден|поздравля|благодар|мем\b|хорошего\s+дня|"
            r"красив\w*\s+(закат|двор)"
        ),
        "social",
    ),
    (re.compile(r"(?i)концерт|фестиваль|кофейн|скидк|открылась\s+нов"), "promo"),
    (re.compile(r"(?i)субботник|приглашаем\s+на\s+праздник"), "optional_event"),
    (
        re.compile(r"(?i)показан\w*\s+сч[её]т|квитанц|госуслуги\s+дом|оплат\w*\s+(жку|счет|жил)"),
        "bills",
    ),
    (re.compile(r"(?i)мошенничеств|клади\s+трубку"), "scam_info"),
]

_DISASTER = [
    re.compile(r"(?i)землетрясен|цунами|\bтеракт|утечка\s+хлора|хим\w*\s+авар"),
    re.compile(r"(?i)ядерн\w*\s+(тревог|удар|авар|катастроф)|радиоактив"),
    re.compile(r"(?i)прорыв\s+(дамб|плотин)|режим\s+чс|\bввед[её]н\w*\s+режим\s+чс"),
    re.compile(
        r"(?i)объявлен\w*\s+чрезвычайн|режим\s+чрезвычайн|"
        r"чрезвычайн\w*\s+ситуац\w*\s+(введ|объяв|из-за)"
    ),
    re.compile(r"(?i)под\s+завалами|захват\s+заложник|массовое\s+отравление"),
    re.compile(r"(?i)сход\s+поезда|лесной\s+пожар|магнитуд"),
    re.compile(
        r"(?i)(пожар|взрыв|авар|эвакуац|разлив).{0,40}нефтебаз|"
        r"нефтебаз.{0,40}(пожар|взрыв|авар|эвакуац|разлив|бпла)"
    ),
    re.compile(r"(?i)объявлена\s+срочная\s+эвакуац|катастроф"),
    re.compile(r"(?i)ракетн\w*\s+опасност|воздушн\w*\s+тревог"),
]

_PROMO_RESCUE = re.compile(
    r"(?i)гочсипб|департамент\w*\s+по\s+делам\s+граждан|"
    r"пожарно[- ]?спасательн\w*\s+центр|"
    r"чемпионат\w*.{0,40}спасател|соревнован\w*.{0,40}спасател|"
    r"профориентац|открыт\w*\s+урок\w*.{0,30}безопасност|"
    r"учебно[- ]?консультационн|"
    r"зоопарк|ночь\s+летучих|"
    r"музей\s+городского\s+хозяйства|"
    r"новогодний\s+экспресс|окц\s+юао|"
    r"конкурс\w*\s+профмастерства|лаборант\w*\s+побед|"
    r"мид\s+(решительно\s+)?(осудил|назвал)|терактам?\s+против\s+избиратель"
)

_AMBIGUOUS = re.compile(r"(?i)^.{0,25}\b(пожар\w*|затопило|нож|газ\w*)\b.{0,25}$")


@dataclass(frozen=True, slots=True)
class LabelDecision:
    importance: int
    disaster_flag: bool
    confidence: float
    reason: str
    skip: bool = False


def _has_past_done(text: str) -> bool:
    return bool(_PAST_DONE.search(text))


def _match_first(patterns: list[tuple[re.Pattern[str], str]], text: str) -> str | None:
    for pat, name in patterns:
        if pat.search(text):
            return name
    return None


def label_text(text: str) -> LabelDecision:
    """Вернуть решение по критериям; skip=True если нельзя честно разметить."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if len(raw) < 12:
        return LabelDecision(3, False, 0.0, "too_short", skip=True)

    low = raw.lower()
    # снятие режима опасности — полезно знать (cat.2), не срочность
    if re.search(r"(?i)(отмен[её]н\w*|снят\w*)\s+режим\w*\s+«?ракетн", low):
        return LabelDecision(2, False, 0.92, "cat2:danger_lifted")

    # упоминание сигналов опасности в чужом регионе / репортаж — не локальная срочность
    if re.search(r"(?i)ракетн\w*\s+опасност|воздушн\w*\s+тревог", low) and re.search(
        r"(?i)наблюдател|выборы|рассказала|сигналы\s+.{0,20}постоянно|в\s+регионе\s+постоянно",
        low,
    ):
        return LabelDecision(3, False, 0.85, "remote_danger_report")

    if _PROMO_RESCUE.search(low) and not re.search(
        r"(?i)горит|задымлен|заливает|запах\w*\s+газ|объявлен\w*\s+эвакуац\w*\s+из-за",
        low,
    ):
        return LabelDecision(3, False, 0.88, "promo_rescue_org")

    if _EDU_SAFETY.search(low) and not re.search(
        r"(?i)сейчас\s+горит|задымлен|заливает|запах\w*\s+газ", low
    ):
        return LabelDecision(3, False, 0.9, "edu_safety")

    disaster = any(p.search(low) for p in _DISASTER)
    # прошлые теракты / приговоры — не срочность
    if (
        disaster
        and re.search(r"(?i)теракт", low)
        and re.search(
            r"(?i)приговор|осужден|дело\s+о\s+теракте|нет\s+оправдания|накажут|утвердил\w*\s+сроки|"
            r"восстанавливать.{0,40}после\s+теракта",
            low,
        )
    ):
        disaster = False
        if not re.search(r"(?i)сейчас|прямо\s+сейчас|идёт\s+теракт|произош[её]л\s+теракт", low):
            return LabelDecision(3, False, 0.9, "past_terror_news")

    if _NEGATION_OR_DRILL.search(low) and not disaster:
        # учебная проверка сирен → cat 2; мемы про пожар → 3
        if re.search(r"(?i)учебн\w+\s+проверк|проверка\s+сирен", low):
            return LabelDecision(2, False, 0.9, "drill_planned")
        return LabelDecision(3, False, 0.85, "negation_or_joke")

    # --- Category 1 ---
    cat1 = _match_first(_CAT1, low)
    if cat1:
        if cat1 in {
            "fire_word",
            "fire_place",
            "fire_active",
            "smoke",
            "evac",
        } and _FIRE_NON_EVENT.search(low):
            # статья/учения про пожарных → не срочность; может быть cat.3
            pass
        elif cat1 == "violence" and _VIOLENCE_NON_EVENT.search(low):
            pass
        else:
            past = _has_past_done(low)
            after_incident = bool(re.search(r"(?i)после\s+пожар", low))
            # пограничные: потушен / ограничений нет → не 1
            if (past or after_incident) and cat1 in _CAT1_NEED_ACTIVE | {
                "flood_active",
                "violence",
                "knife",
            }:
                # «после пожара запрещён вход / эвакуация» остаётся 1
                if re.search(r"(?i)запрещ[её]н\s+вход|эвакуац|секци\w*\s+закрыт", low):
                    return LabelDecision(1, disaster, 0.9, f"cat1_ongoing_after:{cat1}")
                # «после пожара ремонтируют лифт» → 2
                if re.search(r"(?i)ремонтир|не\s+работает\s+лифт|лифт\s+временно", low):
                    return LabelDecision(2, False, 0.9, f"cat2_aftermath:{cat1}")
                if past:
                    return LabelDecision(3, False, 0.88, f"cat3_resolved:{cat1}")

            # «пожар локализован» без эвакуации — не автоматический «всё ок»
            if re.search(r"(?i)локализован", low) and not re.search(
                r"(?i)эвакуац|горит|задымлен|не\s+входить", low
            ):
                return LabelDecision(2, disaster, 0.7, "fire_localized_unclear", skip=False)

            # очень короткое «там пожар» без места/времени
            if (
                cat1 == "fire_word"
                and len(raw) < 50
                and not re.search(r"(?i)квартир|подъезд|подвал|дом|улиц|двор", low)
            ):
                return LabelDecision(1, disaster, 0.4, "ambiguous_fire", skip=True)

            return LabelDecision(1, disaster, 0.92, f"cat1:{cat1}")

    # fallthrough if fire/violence matched but non-event context

    # активное затопление без слова «пожар»
    if re.search(r"(?i)заливает\s+квартир|вода\s+сейчас\s+залив", low):
        return LabelDecision(1, False, 0.9, "cat1:flood_now")

    # --- Category 2 ---
    cat2 = _match_first(_CAT2, low)
    if cat2:
        # лифт с людьми уже пойман в cat1; пустой — 2
        if cat2 == "elevator_broken" and re.search(r"(?i)люди|застрял|помощ", low):
            return LabelDecision(1, False, 0.93, "cat1:elevator_people")
        return LabelDecision(2, disaster, 0.9, f"cat2:{cat2}")

    # --- Category 3 explicit ---
    cat3 = _match_first(_CAT3, low)
    if cat3:
        return LabelDecision(3, False, 0.9, f"cat3:{cat3}")

    # городская ЧС-маркер без других сигналов → 1 + disaster
    if disaster:
        return LabelDecision(1, True, 0.85, "disaster_keyword")

    # короткий амбиг
    if _AMBIGUOUS.match(raw):
        return LabelDecision(3, False, 0.3, "ambiguous_short", skip=True)

    # новости/общий болт без инфраструктурного действия → 3
    return LabelDecision(3, False, 0.75, "default_info")
