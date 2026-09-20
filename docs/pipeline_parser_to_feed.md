# Пайплайн: парсер → Events → лента

Та же схема, что в [`pipeline_parser_to_feed.puml`](./pipeline_parser_to_feed.puml), в **Mermaid**.

```mermaid
flowchart TB
  subgraph PARSER["Парсер-воркер · parse_news / parse_mc / chat"]
    A[Fetch RSS / HTML / УК] --> B[RawNewsArticle / RawMcNotice]
    B --> C{Иностранная география?}
    C -->|да| SKIP([Skip — не в events])
    C -->|нет| GEO
  end

  subgraph GEO["Гео до Candidate"]
    direction TB
    G1[Поля источника city/street/house]
    G2[regex + spaCy LOC hints]
    G3[StreetCatalog stem+fuzzy → addresses]
    G4[Дефолт Москва · только локальные СМИ/УК]
    G5[MC: fan-out — событие на каждую улицу]
    G1 --> G2 --> G3 --> G4
    G3 --> G5
  end

  C -->|нет| G1
  G4 --> CAND[ParserCandidate]
  G5 --> CAND

  subgraph NORM["parser_common.normalize · KAN-13"]
    N1[title/body · эвристика]
    N2[importance ONNX → rules<br/>disaster · keywords]
    N3[active_from / active_to · ML time<br/>без ONNX → null]
    N4{address_id уже есть?}
    N5[place_ner fallback<br/>spaCy+catalog / GeoMatcher]
    N6[Оставить geo воркера]
    N1 --> N2 --> N3 --> N4
    N4 -->|нет| N5
    N4 -->|да| N6
    N5 --> DRAFT[EventDraft]
    N6 --> DRAFT
  end

  CAND --> N1

  subgraph DEDUP["ml_dedup.resolve · KAN-19"]
    D1{source + source_msg_id<br/>уже в DB?}
    D2[Пул активных Events<br/>active_days = 21<br/>и не истёкший active_to]
    D3[Embed title+body<br/>ONNX / rubert / hash]
    D4{Cosine score}
    D1 -->|да| DUP1([DUPLICATE · вернуть existing])
    D1 -->|нет| D2 --> D3 --> D4
    D4 -->|≥ T_dup| DUP2([DUPLICATE · не плодим карточку])
    D4 -->|T_upd…T_dup<br/>или near-dup + update-hint| UPD([UPDATE · update_event])
    D4 -->|ниже| NEW([NEW · create_event])
  end

  DRAFT --> D1

  subgraph FEED["events · KAN-14 → лента"]
    E1[(events + addresses<br/>weight)]
    E2{address_id + text<br/>и importance ∈ 1,2?}
    E3{geo_by}
    E4[GET /events/feed?scope=nearby]
    E5[GET /events/feed?scope=city]
    E6[WebApp TikTok-карточка]
    E1 --> E2
    E2 -->|нет| HIDDEN([В DB, но не в ленте])
    E2 -->|да| E3
    E3 -->|street / home| E4 --> E6
    E3 -->|city| E5 --> E6
  end

  DUP1 --> E1
  DUP2 --> E1
  UPD --> E1
  NEW --> E1

  classDef skip fill:#FECACA,stroke:#991B1B,color:#111
  classDef dup fill:#DBEAFE,stroke:#1D4ED8,color:#111
  classDef upd fill:#BBF7D0,stroke:#15803D,color:#111
  classDef neu fill:#A7F3D0,stroke:#047857,color:#111
  classDef hide fill:#FEF3C7,stroke:#B45309,color:#111
  class SKIP,HIDDEN skip
  class DUP1,DUP2 dup
  class UPD upd
  class NEW neu
```

| Исход | Смысл |
|-------|--------|
| **NEW** | новое событие в `events` |
| **UPDATE** | актуализация (устранение причины, продление…) |
| **DUPLICATE** | та же новость — без новой карточки |
| **Skip** | иностранная география |
| **В DB, не в ленте** | нет адреса или `importance=3` |
