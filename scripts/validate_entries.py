import json
from pathlib import Path
from pydantic import TypeAdapter, ValidationError
from askdosm.models import DatasetDefinition

raw = json.loads(Path('data/catalogue_entries_auto.json').read_text(encoding='utf-8'))
print(f'Total entries: {len(raw)}')

valid = 0
errors = []
for i, entry in enumerate(raw):
    try:
        DatasetDefinition.model_validate(entry)
        valid += 1
    except ValidationError as e:
        errors.append({'i': i, 'id': entry.get('dataset_id', '?'), 'error': str(e)[:300]})

print(f'Valid: {valid}/{len(raw)}')
print(f'Errors: {len(errors)}')
for e in errors[:15]:
    print(f'  [{e["i"]}] {e["id"]}: {e["error"][:250]}')