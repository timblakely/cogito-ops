import os,json
from pathlib import Path
for root in ['/ngram/q6','/ngram/davetha','/ngram/strata','/ngram/r9v','/models/iq3/UD-IQ3_XXS','/models/q6/UD-Q6_K_XL']:
 p=Path(root);print(root)
 for f in p.glob('*'):print(f.name,f.stat().st_size, '->'+os.readlink(f) if f.is_symlink() else '')
