from __future__ import annotations

from fastapi import Request
from starlette.datastructures import UploadFile


FormValues = dict[str, list[str]]
UploadedTextFiles = list[tuple[str, str]]


async def read_form(request: Request) -> FormValues:
    form = await request.form()
    values: FormValues = {}
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            continue
        values.setdefault(key, []).append(str(value))
    return values


async def read_form_with_files(request: Request) -> tuple[FormValues, UploadedTextFiles]:
    form = await request.form()
    values: FormValues = {}
    files: UploadedTextFiles = []
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if value.filename:
                content = await value.read()
                files.append((value.filename, content.decode("utf-8-sig", errors="replace")))
            continue
        values.setdefault(key, []).append(str(value))
    return values, files
