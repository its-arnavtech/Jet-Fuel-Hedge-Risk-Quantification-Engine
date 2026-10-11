"""Check publishable text encoding and configured credentials without printing values."""

import os
from pathlib import Path
import re
import subprocess

from fuel_hedge.config import load_env


def main():
    load_env()
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],text=True).splitlines()
    extensions={'.py','.md','.json','.ipynb','.sql','.toml','.lock','.yml','.yaml','.pq','.dax'}
    secrets=[os.environ.get(name,'').encode() for name in ['EIA_API_KEY','DATABRICKS_TOKEN']]
    checked=0
    for name in files:
        path=Path(name)
        if not path.is_file():
            continue
        raw=path.read_bytes()
        if any(secret and secret in raw for secret in secrets):
            raise ValueError('Configured credential in publishable file: '+name)
        if path.suffix in extensions or path.name in {'.env.example','.gitignore'}:
            raw.decode('utf-8')
            if re.search(rb'dapi[0-9a-f]{32}\b',raw):
                raise ValueError('Possible Databricks token in publishable file: '+name)
            checked+=1
    if '.env' in files:
        raise ValueError('Local .env must be ignored')
    print(f'UTF-8 and credential checks passed: {checked} text files, {len(files)} publishable files')


if __name__=='__main__':
    main()
