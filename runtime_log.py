import datetime
import json
from pathlib import Path
import traceback


def event(kind,error=None,**fields):
    record=dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),event=kind,**fields)
    if error is not None:
        record['error_type']=type(error).__name__
        record['locations']=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__)]
    with open('runtime-events.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
