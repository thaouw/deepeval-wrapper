import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File
from typing import List

from ..models.auth import User
from ..models.evaluation import (
    EvaluationRequest,
    BulkEvaluationRequest,
    EvaluationResponse,
    BulkEvaluationResponse,
    AsyncEvaluationResponse,
    DatasetEvaluationRequest,
)
from ..services.deepeval_service import DeepEvalService
from ..services.job_service import JobService
from ..config import settings
from ..auth import get_current_user

router = APIRouter(prefix="/evaluate", tags=["Evaluation"])
deepeval_service = DeepEvalService()
job_service = JobService()


@router.post("/", response_model=EvaluationResponse)
async def evaluate_single(
    evaluation_request: EvaluationRequest,
    current_user: User = Depends(get_current_user)
):
    """Evaluate a single test case synchronously."""
    try:
        result = await deepeval_service.evaluate_single(
            evaluation_request.test_case,
            evaluation_request.metrics
        )
        
        return EvaluationResponse(result=result)
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {str(e)}"
        )


@router.post("/bulk", response_model=BulkEvaluationResponse)
async def evaluate_bulk(
    bulk_request: BulkEvaluationRequest,
    current_user: User = Depends(get_current_user)
):
    """Evaluate multiple test cases synchronously."""
    try:
        evaluation_data = await deepeval_service.evaluate_bulk(
            bulk_request.test_cases,
            bulk_request.metrics,
            max_concurrent=bulk_request.max_concurrent or settings.default_max_concurrent
        )
        
        return BulkEvaluationResponse(
            results=evaluation_data["results"],
            summary=evaluation_data["summary"]
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk evaluation failed: {str(e)}"
        )


@router.post("/async", response_model=AsyncEvaluationResponse)
async def evaluate_async(
    evaluation_request: EvaluationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Start an asynchronous evaluation job for a single test case."""
    # Create job
    job_id = await job_service.create_job(
        job_name=evaluation_request.job_name,
        tags=evaluation_request.tags,
        metadata={"user": current_user.username, "type": "single"}
    )
    
    # Start background task
    background_tasks.add_task(
        _run_async_single_evaluation,
        job_id,
        evaluation_request
    )
    
    job = await job_service.get_job(job_id)
    return AsyncEvaluationResponse(
        job_id=job_id,
        status="pending",
        created_at=job.created_at if job else datetime.now()
    )


@router.post("/async/bulk", response_model=AsyncEvaluationResponse)
async def evaluate_bulk_async(
    bulk_request: BulkEvaluationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Start an asynchronous evaluation job for multiple test cases."""
    # Create job
    job_id = await job_service.create_job(
        job_name=bulk_request.job_name,
        tags=bulk_request.tags,
        metadata={
            "user": current_user.username,
            "type": "bulk",
            "test_case_count": len(bulk_request.test_cases)
        }
    )
    
    # Start background task
    background_tasks.add_task(
        _run_async_bulk_evaluation,
        job_id,
        bulk_request
    )
    
    job = await job_service.get_job(job_id)
    return AsyncEvaluationResponse(
        job_id=job_id,
        status="pending",
        created_at=job.created_at if job else datetime.now()
    )


@router.post("/dataset", response_model=AsyncEvaluationResponse)
async def evaluate_dataset(
    dataset_request: DatasetEvaluationRequest,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Evaluate a dataset from uploaded file."""
    # Validate file size
    if file.size > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size / 1024 / 1024}MB"
        )
    
    # Create job
    job_id = await job_service.create_job(
        job_name=dataset_request.job_name or f"Dataset: {dataset_request.dataset_name}",
        tags=dataset_request.tags,
        metadata={
            "user": current_user.username,
            "type": "dataset",
            "dataset_name": dataset_request.dataset_name,
            "file_name": file.filename
        }
    )
    
    # Start background task
    background_tasks.add_task(
        _run_async_dataset_evaluation,
        job_id,
        dataset_request,
        file
    )
    
    job = await job_service.get_job(job_id)
    return AsyncEvaluationResponse(
        job_id=job_id,
        status="pending",
        created_at=job.created_at if job else datetime.now()
    )


async def _run_async_single_evaluation(job_id: str, request: EvaluationRequest):
    """Background task for single evaluation."""
    try:
        await job_service.update_job_status(job_id, "running")
        await job_service.update_job_progress(job_id, 0, 1, "Starting evaluation...")
        
        result = await deepeval_service.evaluate_single(
            request.test_case,
            request.metrics
        )
        
        await job_service.update_job_progress(job_id, 1, 1, "Evaluation completed")
        
        # Create summary for single result
        from ..models.evaluation import EvaluationSummary
        summary = EvaluationSummary(
            total_test_cases=1,
            successful_test_cases=1 if result.overall_success else 0,
            failed_test_cases=0 if result.overall_success else 1,
            success_rate=1.0 if result.overall_success else 0.0,
            total_execution_time=result.execution_time,
        )
        
        await job_service.complete_job(job_id, [result], summary)
    
    except Exception as e:
        await job_service.fail_job(job_id, str(e))


async def _run_async_bulk_evaluation(job_id: str, request: BulkEvaluationRequest):
    """Background task for bulk evaluation."""
    try:
        await job_service.update_job_status(job_id, "running")
        total_tests = len(request.test_cases)
        await job_service.update_job_progress(job_id, 0, total_tests, "Starting bulk evaluation...")
        
        # Process in batches to provide progress updates
        batch_size = min(request.max_concurrent or 10, 10)
        results = []
        
        for i in range(0, total_tests, batch_size):
            batch = request.test_cases[i:i + batch_size]
            
            # Evaluate batch
            batch_data = await deepeval_service.evaluate_bulk(
                batch,
                request.metrics,
                max_concurrent=batch_size
            )
            
            results.extend(batch_data["results"])
            
            # Update progress
            completed = min(i + batch_size, total_tests)
            await job_service.update_job_progress(
                job_id, completed, total_tests, 
                f"Processed {completed}/{total_tests} test cases"
            )
        
        # Calculate final summary
        final_summary = deepeval_service._calculate_summary(results, 0)
        
        await job_service.complete_job(job_id, results, final_summary)
    
    except Exception as e:
        await job_service.fail_job(job_id, str(e))


async def _run_async_dataset_evaluation(
    job_id: str, 
    request: DatasetEvaluationRequest, 
    file: UploadFile
):
    """Background task for dataset evaluation."""
    try:
        await job_service.update_job_status(job_id, "running")
        await job_service.update_job_progress(job_id, 0, 100, "Processing dataset file...")
        
        # Read and parse file
        content = await file.read()
        test_cases = await _parse_dataset_file(content, file.filename, request)
        
        total_tests = len(test_cases)
        await job_service.update_job_progress(
            job_id, 10, 100, f"Parsed {total_tests} test cases. Starting evaluation..."
        )
        
        # Run evaluation
        evaluation_data = await deepeval_service.evaluate_bulk(
            test_cases,
            request.metrics,
            max_concurrent=request.max_concurrent or settings.default_max_concurrent
        )
        
        await job_service.update_job_progress(job_id, 90, 100, "Finalizing results...")
        
        await job_service.complete_job(
            job_id,
            evaluation_data["results"],
            evaluation_data["summary"]
        )
    
    except Exception as e:
        await job_service.fail_job(job_id, str(e))


async def _parse_dataset_file(content: bytes, filename: str, request: DatasetEvaluationRequest) -> List:
    """Parse dataset file into test cases."""
    import pandas as pd
    import json
    from io import StringIO, BytesIO
    
    # Determine file format
    file_format = request.file_format
    if file_format == "auto":
        if filename.endswith('.csv'):
            file_format = "csv"
        elif filename.endswith(('.json', '.jsonl')):
            file_format = "json"
        else:
            raise ValueError("Could not determine file format. Please specify file_format.")
    
    # Parse file
    if file_format == "csv":
        df = pd.read_csv(StringIO(content.decode('utf-8')))
        data = df.to_dict('records')
    elif file_format == "json":
        content_str = content.decode('utf-8')
        if filename.endswith('.jsonl'):
            # JSON Lines format
            data = [json.loads(line) for line in content_str.strip().split('\n')]
        else:
            # Regular JSON
            data = json.loads(content_str)
            if not isinstance(data, list):
                data = [data]
    else:
        raise ValueError(f"Unsupported file format: {file_format}")
    
    # Convert to test cases
    from ..models.test_cases import LLMTestCaseRequest
    test_cases = []
    
    column_mapping = request.column_mapping or {}
    
    for row in data:
        # Map columns to test case fields
        mapped_row = {}
        for field, column in column_mapping.items():
            if column in row:
                mapped_row[field] = row[column]
        
        # Use direct field names if no mapping provided
        if not column_mapping:
            mapped_row = row
        
        # Create test case
        test_case = LLMTestCaseRequest(
            input=mapped_row.get('input', ''),
            actual_output=mapped_row.get('actual_output', ''),
            expected_output=mapped_row.get('expected_output'),
            retrieval_context=mapped_row.get('retrieval_context'),
            context=mapped_row.get('context'),
        )
        test_cases.append(test_case)
    
    return test_cases
