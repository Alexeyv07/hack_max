# ML вне src

Обучение и артефакты **не** кладём в `src/`.

- **importance classify (KAN-13):** [`classify/MODEL.md`](./classify/MODEL.md)
- **dedup embeddings (KAN-19):** `dedup/` (позже)

```bash
pip install -e ".[ml]"
python ml/classify/train_torch.py
```
