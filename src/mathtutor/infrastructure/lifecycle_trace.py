"""Opt-in lifecycle metadata; never emit paths, SQL, parameters or messages."""
import asyncio
import json
import logging
import os
import threading
import traceback


def trace(owner, stage, *, error=None, **metadata):
    if not os.environ.get("MATHTUTOR_LIFECYCLE_TRACE"):
        return
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    row = dict(owner=str(owner), stage=stage, process=os.getpid(),
               thread=threading.get_ident(), task=id(task) if task else None, **metadata)
    if error is not None:
        row["error_type"] = type(error).__name__
        row["frames"] = [dict(function=f.name, line=f.lineno)
                         for f in traceback.extract_tb(error.__traceback__)]
    logging.getLogger("mathtutor.lifecycle").warning(json.dumps(row, sort_keys=True))
