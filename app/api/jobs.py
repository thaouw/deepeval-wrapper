from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..models.auth import User
from ..models.evaluation import JobStatus, AsyncEvaluationResponse, JobListResponse
from ..services.job_service import JobService
from ..auth import get_current_user, get_current_admin_user

router = APIRouter(prefix="/jobs", tags=["Jobs"])
job_service = JobService()


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[JobStatus] = Query(None, description="Filter by job status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    current_user: User = Depends(get_current_user)
):
    """List evaluation jobs with pagination and filtering."""
    return await job_service.list_jobs(
        page=page,
        page_size=page_size,
        status_filter=status,
        tag_filter=tag
    )


@router.get("/{job_id}", response_model=AsyncEvaluationResponse)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get evaluation job by ID."""
    job = await job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """Cancel a running evaluation job."""
    success = await job_service.cancel_job(job_id)
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Job not found or cannot be cancelled"
        )
    
    return {"message": "Job cancelled successfully"}


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete an evaluation job."""
    success = await job_service.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"message": "Job deleted successfully"}


@router.get("/stats/summary")
async def get_job_stats(
    current_user: User = Depends(get_current_user)
):
    """Get job statistics summary."""
    return job_service.get_job_stats()


@router.post("/cleanup")
async def cleanup_old_jobs(
    max_age_days: int = Query(7, ge=1, le=365, description="Maximum age in days"),
    current_user: User = Depends(get_current_admin_user)  # Admin only
):
    """Clean up old completed jobs."""
    deleted_count = await job_service.cleanup_old_jobs(max_age_days)
    return {"message": f"Cleaned up {deleted_count} old jobs"}
