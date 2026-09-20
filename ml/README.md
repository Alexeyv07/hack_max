# ML вне src

Обучение и артефакты **не** кладём в `src/`. Пакет `ml/` из runtime не импортировать.

| трек | каталог | задача |
|------|---------|--------|
| importance classify (KAN-13) | [`classify/`](./classify/) | `importance` 1\|2\|3 → ONNX |
| time window (KAN-19) | [`time/`](./time/) | `active_from` / `active_to` (offsets) |
| dedup embeddings (KAN-19) | [`dedup/`](./dedup/) | cosine пороги duplicate\|update\|unrelated |

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"

# classify
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml

# time window
python ml/time/bootstrap_data.py
python ml/time/train_torch.py --config ml/time/config_torch.yaml

# dedup thresholds
python ml/dedup/bootstrap_pairs.py
python ml/dedup/eval_threshold.py --pairs ml/dedup/data/bootstrap_pairs.jsonl
```

Подробности: `classify/README.md`, `time/README.md`, `dedup/README.md`.
