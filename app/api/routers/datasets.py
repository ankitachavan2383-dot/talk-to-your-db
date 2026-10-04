from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.analysis.profiler import profile_dataframe
from app.api.deps import get_svc
from app.core.serialization import df_to_records, sanitize
from app.core.services import Services
from app.data.loader import LoadError, load_dataframe, save_original

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("")
def upload_dataset(file: UploadFile = File(...), svc: Services = Depends(get_svc)):
    content = file.file.read(svc.settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        path, ftype = save_original(content, file.filename or "upload", svc.settings.uploads_dir, svc.settings.max_upload_mb)
        df = load_dataframe(path)
    except LoadError as exc:
        raise HTTPException(400, str(exc)) from exc
    profile = sanitize(profile_dataframe(df))
    ds = svc.repo.add_dataset(name=file.filename, file_type=ftype, stored_path=str(path), n_rows=len(df), n_cols=df.shape[1], profile=profile)
    return {"id": ds["id"], "name": ds["name"], "rows": ds["n_rows"], "cols": ds["n_cols"], "profile": profile}


@router.get("")
def list_datasets(svc: Services = Depends(get_svc)):
    return sanitize(svc.repo.list_datasets())


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: int, svc: Services = Depends(get_svc)):
    ds = svc.repo.get_dataset(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    return ds["profile"]


@router.get("/{dataset_id}/preview")
def preview(dataset_id: int, rows: int = 50, svc: Services = Depends(get_svc)):
    try:
        return df_to_records(svc.dataset_frame(dataset_id), min(rows, 500))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
