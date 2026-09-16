# ML / research вне src/
#
# Сюда кладём обучение, датасеты, чекпоинты, эксперименты.
# Рантайм (src/parser_common) читает только лёгкий rules.yaml при наличии.
#
# Структура:
#   ml/classify/rules.yaml     — опциональные keywords (подхватывает classify)
#   ml/classify/train_stub.py  — заготовка под обучение tiny-классификатора
#   ml/classify/data/          — датасеты (gitignore)
#   ml/classify/checkpoints/   — веса (gitignore)
#   ml/dedup/                   — будущее под KAN-19 embeddings

**Не импортировать пакеты из ml/ в src.** Обучение запускается отдельно:

```bash
python ml/classify/train_stub.py
```
