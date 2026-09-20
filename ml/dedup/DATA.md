# Dedup — данные (пары текстов)

Разметка пар для порогов cosine-similarity: **duplicate** | **update** | **unrelated**.

Используется в KAN-19 (хук около `create_event`): решить, новый кандидат —
дубль существующего события, обновление того же инцидента, или независимая новость.

## Формат строки JSONL

```json
{
  "text_a": "Отключили горячую воду на Ленина до вечера",
  "text_b": "На ул. Ленина нет ГВС до 18:00",
  "label": "duplicate",
  "source": "synthetic"
}
```

| поле | обязательно | смысл |
|------|-------------|--------|
| `text_a` | да | первый текст (кандидат / событие A) |
| `text_b` | да | второй текст (событие B / кандидат) |
| `label` | да | `duplicate` \| `update` \| `unrelated` |
| `source` | нет | `synthetic` / `news` / `mc` / `manual` |

Порядок `a`/`b` не важен для cosine; для единообразия в разметке
`text_a` — более ранний / «старое событие», `text_b` — новый кандидат.

## Классы

| label | смысл | ожидание по cosine |
|-------|-------|---------------------|
| `duplicate` | то же событие, пересказ / зеркало СМИ | высокий |
| `update` | то же происшествие, но новые факты (сроки, масштаб) | средний |
| `unrelated` | разные события / разный адрес / другая тема | низкий |

Граница duplicate↔update субъективна: если тексты взаимозаменяемы в ленте —
`duplicate`; если второе сообщение стоит как «обновление» (новые часы, «устранён») —
`update`.

## Файлы в `ml/dedup/data/`

| файл | роль |
|------|------|
| `pairs.jsonl` | основная разметка пар (user-supplied) |
| `bootstrap_pairs.jsonl` | синтетика из `bootstrap_pairs.py` |
| `val_pairs.jsonl` | опционально для отдельного eval |

`data/.gitkeep` держит каталог в git; сами JSONL в gitignore.

## Объёмы

| цель | пар | баланс |
|------|-----|--------|
| smoke порогов | ~100–200 | `bootstrap_pairs.py` |
| MVP | 500–1.5k | ~1:1:2 (dup:update:unrelated) |
| дальше | 3k+ | больше hard-negatives (похожий адрес, другая авария) |

## Синтетика

```bash
python ml/dedup/bootstrap_pairs.py
# → data/bootstrap_pairs.jsonl
```

Не перезаписывает `pairs.jsonl`. Для smoke eval:

```bash
python ml/dedup/eval_threshold.py --pairs ml/dedup/data/bootstrap_pairs.jsonl
```

## Чеклист

- [ ] три класса представлены
- [ ] есть near-duplicates (парафраз), не только точные копии
- [ ] unrelated включает похожие по теме, но разные адреса/дни
- [ ] JSONL валиден (см. загрузку в `eval_threshold.py`)
