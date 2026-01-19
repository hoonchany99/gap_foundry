"""
Gap Foundry API Server

FastAPI 기반 웹 서비스 백엔드:
- POST /validate: 아이디어 검증 요청 (비동기 처리)
- GET /status/{run_id}: 실행 상태 조회
- GET /report/{run_id}: 완성된 리포트 조회
- GET /stream/{run_id}: SSE 실시간 진행 상태 스트림
- POST /pregate: PreGate만 빠르게 체크 (동기)

Usage:
    uvicorn gap_foundry.api:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from pathlib import Path
from enum import Enum
import uuid
import json
import asyncio
import re
from datetime import datetime

# Gap Foundry 엔진 임포트
from gap_foundry.main import (
    run_gap_foundry_engine,
    _pregate_check,
    _generate_run_id,
    PreGateResult,
)

# ============================================================================
# FastAPI App 설정
# ============================================================================

app = FastAPI(
    title="Gap Foundry API",
    description="AI-powered Market Validation Engine - 아이디어의 초기 검증 가치를 판단합니다",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 설정 (개발용 - 프로덕션에서는 origin 제한 필요)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js 개발 서버
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Pydantic 모델
# ============================================================================

class BusinessType(str, Enum):
    B2B = "B2B"
    B2C = "B2C"
    B2B2C = "B2B2C"


class GeoMarket(str, Enum):
    KR = "KR"
    US = "US"
    GLOBAL = "Global"


class ValidationRequest(BaseModel):
    """아이디어 검증 요청"""
    idea_one_liner: str = Field(..., min_length=5, description="아이디어 한 줄 요약")
    target_customer: str = Field(..., min_length=2, description="타깃 고객")
    problem_statement: str = Field(..., min_length=5, description="해결하려는 문제")
    current_alternatives: str = Field(..., description="현재 대안들")
    geo_market: GeoMarket = Field(default=GeoMarket.KR, description="목표 시장")
    business_type: BusinessType = Field(default=BusinessType.B2B, description="비즈니스 유형")
    constraints: Optional[str] = Field(default="특별한 제약 없음", description="제약 조건")
    success_definition: Optional[str] = Field(
        default="경쟁사 대비 명확한 차별점 도출", 
        description="성공 정의"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "idea_one_liner": "대기업 인사팀을 위한 직원 심리 상태 예측 AI 대시보드",
                "target_customer": "직원 수 1,000명 이상 대기업의 인사(HR)팀",
                "problem_statement": "조직 내 번아웃이나 이직 징후를 사전에 파악하기 어렵다",
                "current_alternatives": "연 1~2회 직원 만족도 설문이나 퇴사자 면담에 의존",
                "geo_market": "KR",
                "business_type": "B2B"
            }
        }


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREGATE_CHECKING = "pregate_checking"
    PREGATE_FAILED = "pregate_failed"
    RESEARCHING = "researching"
    ANALYZING = "analyzing"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    FAILED = "failed"


class ValidationStatus(BaseModel):
    """검증 작업 상태"""
    run_id: str
    status: JobStatus
    progress: int = Field(default=0, ge=0, le=100, description="진행률 (0-100)")
    current_step: Optional[str] = Field(default=None, description="현재 진행 중인 단계")
    verdict: Optional[str] = Field(default=None, description="최종 판정 (GO/HOLD/NO)")
    created_at: str
    updated_at: Optional[str] = None
    report_url: Optional[str] = None
    error_message: Optional[str] = None


class PreGateRequest(BaseModel):
    """PreGate 빠른 체크 요청"""
    idea_one_liner: str
    target_customer: str
    problem_statement: str
    current_alternatives: Optional[str] = ""


class PreGateResponse(BaseModel):
    """PreGate 체크 결과"""
    is_valid: bool
    score: float = Field(description="구체성 점수 (0.0-1.0)")
    fail_reasons: List[str]
    warnings: List[str]
    suggestions: List[str] = Field(default_factory=list, description="개선 제안")


class ReportResponse(BaseModel):
    """리포트 응답"""
    run_id: str
    verdict: str
    report_markdown: str
    report_html: Optional[str] = None
    created_at: str


# ============================================================================
# 인메모리 상태 저장소 (프로덕션에서는 Redis/DB 권장)
# ============================================================================

jobs: Dict[str, Dict[str, Any]] = {}
job_logs: Dict[str, List[str]] = {}  # SSE용 로그


def _update_job_status(
    run_id: str, 
    status: JobStatus, 
    progress: int = 0,
    current_step: str = None,
    verdict: str = None,
    error_message: str = None,
    report_path: str = None,
):
    """작업 상태 업데이트 (내부용)"""
    if run_id not in jobs:
        return
    
    jobs[run_id].update({
        "status": status.value,
        "progress": progress,
        "current_step": current_step,
        "updated_at": datetime.now().isoformat(),
    })
    
    if verdict:
        jobs[run_id]["verdict"] = verdict
    if error_message:
        jobs[run_id]["error_message"] = error_message
    if report_path:
        jobs[run_id]["report_path"] = report_path
    
    # SSE 로그 추가
    log_msg = f"[{progress}%] {current_step or status.value}"
    if run_id not in job_logs:
        job_logs[run_id] = []
    job_logs[run_id].append(log_msg)


# ============================================================================
# API 엔드포인트
# ============================================================================

@app.get("/")
async def root():
    """API 상태 확인"""
    return {
        "name": "Gap Foundry API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.post("/pregate", response_model=PreGateResponse)
async def check_pregate(request: PreGateRequest):
    """
    PreGate 빠른 체크 (동기)
    
    LLM을 호출하지 않고 입력의 구체성만 빠르게 검사합니다.
    실시간 피드백에 적합합니다.
    """
    inputs = {
        "idea_one_liner": request.idea_one_liner,
        "target_customer": request.target_customer,
        "problem_statement": request.problem_statement,
        "current_alternatives": request.current_alternatives or "",
    }
    
    result: PreGateResult = _pregate_check(inputs)
    
    # 개선 제안 생성
    suggestions = []
    if not result.is_valid:
        if any("타깃" in r for r in result.fail_reasons):
            suggestions.append("타깃을 더 구체적으로: '모든 사람' → '야근이 잦은 30대 직장인'")
        if any("문제" in r or "상식" in r for r in result.fail_reasons):
            suggestions.append("문제를 구체적 상황으로: '건강이 중요하다' → '밤 10시 이후 과식을 후회한다'")
        if any("행동" in r for r in result.fail_reasons):
            suggestions.append("구체적 행동 추가: '돕는 앱' → '섭취 칼로리를 자동으로 기록하는 앱'")
    
    return PreGateResponse(
        is_valid=result.is_valid,
        score=result.score,
        fail_reasons=result.fail_reasons,
        warnings=result.warnings,
        suggestions=suggestions,
    )


@app.post("/validate", response_model=ValidationStatus)
async def validate_idea(request: ValidationRequest, background_tasks: BackgroundTasks):
    """
    아이디어 검증 요청 (비동기)
    
    CrewAI 기반 전체 분석을 실행합니다.
    - 경쟁사 리서치
    - 채널/VP 분석
    - 빈틈 발굴
    - Red Team 검토
    - 최종 리포트 생성
    
    소요 시간: 약 10-15분
    """
    inputs = request.model_dump()
    run_id = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    
    # 작업 초기화
    jobs[run_id] = {
        "status": JobStatus.QUEUED.value,
        "progress": 0,
        "current_step": "대기 중",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "inputs": inputs,
        "verdict": None,
        "report_path": None,
        "error_message": None,
    }
    job_logs[run_id] = []
    
    # 백그라운드 실행
    background_tasks.add_task(run_validation_job, run_id, inputs)
    
    return ValidationStatus(
        run_id=run_id,
        status=JobStatus.QUEUED,
        progress=0,
        current_step="작업이 큐에 추가되었습니다",
        created_at=jobs[run_id]["created_at"],
    )


@app.get("/status/{run_id}", response_model=ValidationStatus)
async def get_status(run_id: str):
    """작업 상태 조회"""
    if run_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {run_id}")
    
    job = jobs[run_id]
    
    return ValidationStatus(
        run_id=run_id,
        status=JobStatus(job["status"]),
        progress=job.get("progress", 0),
        current_step=job.get("current_step"),
        verdict=job.get("verdict"),
        created_at=job["created_at"],
        updated_at=job.get("updated_at"),
        report_url=f"/report/{run_id}" if job.get("report_path") else None,
        error_message=job.get("error_message"),
    )


@app.get("/stream/{run_id}")
async def stream_progress(run_id: str):
    """
    SSE (Server-Sent Events) 실시간 진행 상태 스트림
    
    프론트엔드에서 EventSource로 연결하여 실시간 업데이트를 받습니다.
    """
    if run_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {run_id}")
    
    async def event_generator():
        last_log_index = 0
        
        while True:
            if run_id not in jobs:
                break
            
            job = jobs[run_id]
            
            # 새 로그 전송
            logs = job_logs.get(run_id, [])
            for i in range(last_log_index, len(logs)):
                yield f"data: {json.dumps({'type': 'log', 'message': logs[i]})}\n\n"
            last_log_index = len(logs)
            
            # 상태 전송
            status_data = {
                "type": "status",
                "status": job["status"],
                "progress": job.get("progress", 0),
                "current_step": job.get("current_step"),
                "verdict": job.get("verdict"),
            }
            yield f"data: {json.dumps(status_data)}\n\n"
            
            # 완료/실패 시 종료
            if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.PREGATE_FAILED.value]:
                yield f"data: {json.dumps({'type': 'done', 'status': job['status']})}\n\n"
                break
            
            await asyncio.sleep(2)  # 2초마다 업데이트
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/report/{run_id}")
async def get_report(run_id: str):
    """완성된 리포트 조회 (Markdown)"""
    if run_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {run_id}")
    
    job = jobs[run_id]
    
    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Report not ready. Current status: {job['status']}"
        )
    
    report_path = job.get("report_path")
    if not report_path or not Path(report_path).exists():
        # 대체 경로 시도
        reports_dir = Path("outputs/reports")
        matching = list(reports_dir.glob(f"*{run_id}*_report.md"))
        if matching:
            report_path = str(matching[0])
        else:
            raise HTTPException(status_code=404, detail="Report file not found")
    
    report_content = Path(report_path).read_text(encoding="utf-8")
    
    # Verdict 추출
    verdict_match = re.search(r"(LANDING_GO|LANDING_HOLD|LANDING_NO)", report_content)
    verdict = verdict_match.group(1) if verdict_match else "UNKNOWN"
    
    return ReportResponse(
        run_id=run_id,
        verdict=verdict,
        report_markdown=report_content,
        created_at=job["created_at"],
    )


@app.get("/report/{run_id}/download")
async def download_report(run_id: str):
    """리포트 파일 다운로드"""
    if run_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {run_id}")
    
    job = jobs[run_id]
    report_path = job.get("report_path")
    
    if not report_path or not Path(report_path).exists():
        reports_dir = Path("outputs/reports")
        matching = list(reports_dir.glob(f"*{run_id}*_report.md"))
        if matching:
            report_path = str(matching[0])
        else:
            raise HTTPException(status_code=404, detail="Report file not found")
    
    return FileResponse(
        path=report_path,
        filename=Path(report_path).name,
        media_type="text/markdown",
    )


@app.get("/jobs")
async def list_jobs(limit: int = 20):
    """최근 작업 목록 조회"""
    sorted_jobs = sorted(
        jobs.items(),
        key=lambda x: x[1].get("created_at", ""),
        reverse=True
    )[:limit]
    
    return [
        {
            "run_id": run_id,
            "status": job["status"],
            "verdict": job.get("verdict"),
            "created_at": job["created_at"],
            "idea_preview": job.get("inputs", {}).get("idea_one_liner", "")[:50],
        }
        for run_id, job in sorted_jobs
    ]


# ============================================================================
# 백그라운드 작업 실행
# ============================================================================

def run_validation_job(run_id: str, inputs: Dict[str, Any]):
    """
    백그라운드에서 검증 작업 실행
    
    main.py의 run_gap_foundry_engine을 호출하며,
    진행 상태를 jobs dict에 업데이트합니다.
    """
    try:
        # PreGate 체크
        _update_job_status(run_id, JobStatus.PREGATE_CHECKING, 5, "입력 구체성 검사 중...")
        
        pregate_result = _pregate_check(inputs)
        
        if not pregate_result.is_valid:
            _update_job_status(
                run_id, 
                JobStatus.PREGATE_FAILED, 
                100,
                "입력이 너무 모호합니다",
                verdict="LANDING_NO",
                error_message="; ".join(pregate_result.fail_reasons),
            )
            return
        
        # 리서치 단계
        _update_job_status(run_id, JobStatus.RESEARCHING, 15, "경쟁사 리서치 중...")
        
        # Args 객체 생성 (main.py 호환)
        class WebArgs:
            def __init__(self):
                self.out_dir = "outputs"
                self.auto_revise = True
                self.revise_no = False
                self.safe_mode = True
                self.chat = False
                self.out = ""
                self.dry_run = False
        
        args = WebArgs()
        
        # 진행 상태 업데이트 콜백 (향후 확장용)
        def progress_callback(step: str, progress: int):
            if "경쟁사" in step or "discover" in step.lower():
                _update_job_status(run_id, JobStatus.RESEARCHING, progress, step)
            elif "분석" in step or "analyze" in step.lower():
                _update_job_status(run_id, JobStatus.ANALYZING, progress, step)
            elif "리포트" in step or "report" in step.lower():
                _update_job_status(run_id, JobStatus.GENERATING_REPORT, progress, step)
        
        # 단계별 진행 상태 시뮬레이션 (실제로는 crew 내부에서 콜백 호출 필요)
        _update_job_status(run_id, JobStatus.RESEARCHING, 20, "경쟁사 발굴 중...")
        
        # 엔진 실행
        exit_code = run_gap_foundry_engine(inputs, args, custom_run_id=run_id)
        
        if exit_code == 0:
            # 성공 - 리포트 경로 찾기
            reports_dir = Path("outputs/reports")
            matching = list(reports_dir.glob(f"*{run_id}*_report.md"))
            report_path = str(matching[0]) if matching else None
            
            # Verdict 추출
            verdict = "UNKNOWN"
            if report_path and Path(report_path).exists():
                content = Path(report_path).read_text(encoding="utf-8")
                match = re.search(r"(LANDING_GO|LANDING_HOLD|LANDING_NO)", content)
                if match:
                    verdict = match.group(1)
            
            _update_job_status(
                run_id, 
                JobStatus.COMPLETED, 
                100,
                "검증 완료!",
                verdict=verdict,
                report_path=report_path,
            )
        
        elif exit_code == 3:
            # PreGate 실패 (이미 처리됨, 여기 도달 안 함)
            _update_job_status(
                run_id,
                JobStatus.PREGATE_FAILED,
                100,
                "입력 구체화 필요",
                verdict="LANDING_NO",
            )
        
        else:
            # 기타 오류
            _update_job_status(
                run_id,
                JobStatus.FAILED,
                100,
                f"실행 오류 (exit code: {exit_code})",
                error_message=f"Engine returned exit code {exit_code}",
            )
    
    except Exception as e:
        import traceback
        _update_job_status(
            run_id,
            JobStatus.FAILED,
            100,
            "시스템 오류",
            error_message=str(e),
        )
        print(f"[ERROR] Job {run_id}: {traceback.format_exc()}")


# ============================================================================
# 서버 실행
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
