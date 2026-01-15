from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# .env 파일 자동 로드
try:
    from dotenv import load_dotenv
    # 프로젝트 루트의 .env 파일 로드
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv가 없으면 수동으로 로드 시도
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

from gap_foundry.crew import Step1CrewFactory
from gap_foundry.input_refiner import refine_inputs


REQUIRED_KEYS = [
    "idea_one_liner",
    "target_customer",
    "problem_statement",
    "current_alternatives",
    "geo_market",
    "business_type",
]

# 선택적 필드 (기본값 제공)
OPTIONAL_FIELDS = {
    "constraints": "특별한 제약 없음",
    "success_definition": "경쟁사 대비 명확한 차별점 도출",
}


def _load_inputs_from_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object/dict.")
    return data


def _prompt_missing_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    for k in REQUIRED_KEYS:
        if not data.get(k):
            data[k] = input(f"{k}: ").strip()
    return data


def _validate_inputs(data: Dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_KEYS if not data.get(k)]
    if missing:
        raise ValueError(f"Missing required input keys: {missing}")


# ============================================================================
# 운영급 가드레일 #2: 경쟁사 수 후처리 강제 컷
# ============================================================================

MAX_COMPETITORS_ITEMS = 8  # items 최대 8개
MAX_COMPETITORS_CANDIDATES = 15  # candidates 최대 15개


def _compact_competitors_output(raw_output: str) -> Tuple[str, bool]:
    """
    discover_competitors 출력을 파싱해서 강제 컷한다.
    
    Returns:
        (compacted_output, was_truncated)
    """
    # JSON 추출 시도
    json_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_output, re.IGNORECASE)
    if not json_match:
        # JSON 블록이 없으면 { ... } 찾기
        first = raw_output.find("{")
        last = raw_output.rfind("}")
        if 0 <= first < last:
            json_str = raw_output[first:last + 1]
        else:
            return raw_output, False
    else:
        json_str = json_match.group(1)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return raw_output, False
    
    was_truncated = False
    
    # items 강제 컷
    if "items" in data and isinstance(data["items"], list):
        if len(data["items"]) > MAX_COMPETITORS_ITEMS:
            data["items"] = data["items"][:MAX_COMPETITORS_ITEMS]
            was_truncated = True
    
    # candidates 강제 컷
    if "candidates" in data and isinstance(data["candidates"], list):
        if len(data["candidates"]) > MAX_COMPETITORS_CANDIDATES:
            data["candidates"] = data["candidates"][:MAX_COMPETITORS_CANDIDATES]
            was_truncated = True
    
    # notes 필드 제거 (불필요한 컨텍스트 감소)
    for item in data.get("items", []):
        if isinstance(item, dict) and "notes" in item:
            # notes를 1줄로 축약
            notes = item.get("notes", "")
            if isinstance(notes, str) and len(notes) > 50:
                item["notes"] = notes[:50] + "..."
    
    compacted = "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
    return compacted, was_truncated


# ============================================================================
# 운영급 가드레일 #5: Preflight 안전 점검
# ============================================================================

CONTEXT_SIZE_THRESHOLD = 15000  # 15k 문자 넘으면 위험


def _preflight_check(crew, safe_mode: bool = False) -> Dict[str, Any]:
    """
    실행 전 context 크기를 체크하고, 위험하면 경고/자동 축소.
    
    Returns:
        {
            "total_chars": int,
            "is_safe": bool,
            "warnings": list[str],
            "auto_adjusted": bool,
        }
    """
    result = {
        "total_chars": 0,
        "is_safe": True,
        "warnings": [],
        "auto_adjusted": False,
    }
    
    # 이미 실행된 태스크 결과들의 크기 합산
    tasks = getattr(crew, "tasks", [])
    for task in tasks:
        output = getattr(task, "output", None)
        if output:
            raw = getattr(output, "raw", "") or ""
            result["total_chars"] += len(raw)
    
    # 임계치 체크
    if result["total_chars"] > CONTEXT_SIZE_THRESHOLD:
        result["is_safe"] = False
        result["warnings"].append(
            f"⚠️ 현재 context 크기: {result['total_chars']:,}자 (임계치: {CONTEXT_SIZE_THRESHOLD:,}자)"
        )
        
        if safe_mode:
            # safe_mode에서는 자동 축소 플래그만 설정 (실제 축소는 caller가 처리)
            result["auto_adjusted"] = True
            result["warnings"].append("🔧 Safe Mode: 자동 축소 적용됨")
    
    return result


def _print_preflight_warnings(preflight_result: Dict[str, Any]) -> None:
    """Preflight 경고 출력"""
    if preflight_result["warnings"]:
        print("\n" + "─" * 60)
        print("🔍 Preflight 점검 결과")
        for w in preflight_result["warnings"]:
            print(f"   {w}")
        print("─" * 60 + "\n")


def _safe_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _log_usage_metrics(
    crew, 
    out_dir: Path, 
    run_id: str, 
    elapsed_seconds: Optional[float] = None
) -> Dict[str, Any]:
    """
    CrewAI의 usage_metrics를 추출하여 로깅하고 파일로 저장한다.
    
    CrewAI는 crew.usage_metrics에서 토큰 사용량을 제공한다.
    https://docs.crewai.com/concepts/crews#crew-usage-metrics
    
    Args:
        crew: CrewAI Crew 객체
        out_dir: 출력 디렉토리
        run_id: 실행 ID
        elapsed_seconds: 실행 시간 (초)
    """
    metrics: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "tokens": {},
        "estimated_cost_usd": None,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_formatted": None,
    }
    
    # 실행 시간 포맷팅
    if elapsed_seconds is not None:
        minutes, seconds = divmod(int(elapsed_seconds), 60)
        if minutes > 0:
            metrics["elapsed_formatted"] = f"{minutes}분 {seconds}초"
        else:
            metrics["elapsed_formatted"] = f"{seconds}초"

    # CrewAI usage_metrics 추출
    usage = getattr(crew, "usage_metrics", None)
    if usage:
        # CrewAI의 usage_metrics 구조에 맞게 추출
        if isinstance(usage, dict):
            metrics["tokens"] = usage
        else:
            # UsageMetrics 객체인 경우
            metrics["tokens"] = {
                "total_tokens": getattr(usage, "total_tokens", 0),
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "successful_requests": getattr(usage, "successful_requests", 0),
            }

    # 비용 추정 (대략적인 OpenAI 가격 기준)
    # GPT-4o: $2.50/1M input, $10/1M output
    # GPT-4o-mini: $0.15/1M input, $0.60/1M output
    # 여기서는 평균으로 대략 추정
    total_tokens = metrics["tokens"].get("total_tokens", 0)
    if total_tokens > 0:
        # 혼합 사용 가정: 평균 $1.50/1M tokens (보수적 추정)
        metrics["estimated_cost_usd"] = round(total_tokens * 1.5 / 1_000_000, 4)

    # 콘솔 출력
    print("\n" + "=" * 60)
    print("📊 실행 통계 (Usage Metrics)")
    print("=" * 60)
    
    # 시간 먼저 표시
    if metrics["elapsed_formatted"]:
        print(f"   ⏱️  실행 시간: {metrics['elapsed_formatted']}")
    
    if metrics["tokens"]:
        for k, v in metrics["tokens"].items():
            print(f"   {k}: {v:,}" if isinstance(v, int) else f"   {k}: {v}")
    if metrics["estimated_cost_usd"]:
        print(f"   💰 추정 비용: ${metrics['estimated_cost_usd']:.4f} USD")
    else:
        print("   💰 추정 비용: (데이터 없음)")

    # 파일 저장
    metrics_path = out_dir / "runs" / run_id / "_usage_metrics.json"
    _safe_write_text(metrics_path, json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"   📁 저장됨: {metrics_path}")

    return metrics


# ============================================================================
# 파일명 매핑 (의미 있는 짧은 이름)
# ============================================================================

TASK_FILENAME_MAP = {
    "discover_competitors": "01_경쟁사_발굴",
    "compact_competitors": "02_경쟁사_압축",
    "analyze_channels": "03_채널_분석",
    "extract_value_props": "04_가치제안_추출",
    "summarize_channels_vp": "05_채널VP_요약",
    "mine_gaps": "06_빈틈_발굴",
    "summarize_research": "07_리서치_요약",
    "create_pov_and_positioning": "08_POV_포지셔닝",
    "red_team_review": "09_레드팀_검토",
    "revise_positioning": "10_포지셔닝_수정",
    "red_team_recheck": "11_레드팀_재검토",
    "final_step1_report": "12_최종_리포트",
}

TASK_EMOJI_MAP = {
    "discover_competitors": "🔍",
    "compact_competitors": "📦",
    "analyze_channels": "📢",
    "extract_value_props": "💎",
    "summarize_channels_vp": "📋",
    "mine_gaps": "🕳️",
    "summarize_research": "📑",
    "create_pov_and_positioning": "🎯",
    "red_team_review": "🔴",
    "revise_positioning": "✏️",
    "red_team_recheck": "🔴",
    "final_step1_report": "📊",
}


def _generate_run_id(inputs: Dict[str, Any]) -> str:
    """
    의미 있는 run_id 생성
    형식: YYYY-MM-DD_아이디어요약_타입
    예: 2026-01-16_AI이력서자동작성_B2C
    """
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    
    # 아이디어에서 핵심 단어 추출 (한글/영문, 최대 15자)
    idea = inputs.get("idea_one_liner", "unknown")
    # 공백, 특수문자 제거하고 핵심만
    idea_clean = re.sub(r"[^\w가-힣]", "", idea)[:15]
    
    # 비즈니스 타입
    biz_type = inputs.get("business_type", "")
    
    # 조합
    run_id = f"{date_str}_{idea_clean}"
    if biz_type:
        run_id += f"_{biz_type}"
    
    # 파일시스템 안전하게
    run_id = re.sub(r"[/\\:*?\"<>|]", "_", run_id)
    
    return run_id


def _extract_task_id(task) -> str:
    """
    Task 객체에서 안정적으로 식별자를 뽑기 위한 헬퍼.
    CrewAI 버전에 따라 name/id가 없을 수 있어 description 첫 줄로 대체.
    """
    # 우선순위: name -> id -> description prefix
    name = getattr(task, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()

    tid = getattr(task, "id", None)
    if isinstance(tid, str) and tid.strip():
        return tid.strip()

    desc = getattr(task, "description", "") or ""
    first = desc.strip().splitlines()[0] if desc.strip() else "task"
    first = first[:40].strip().replace(" ", "_")
    return first or "task"


def _get_friendly_filename(task_id: str, index: int) -> str:
    """태스크 ID를 의미 있는 파일명으로 변환"""
    # 매핑에서 찾기
    if task_id in TASK_FILENAME_MAP:
        return TASK_FILENAME_MAP[task_id]
    
    # 매핑에 없으면 기본 형태
    return f"{index:02d}_{task_id[:30]}"


def _generate_task_header(task_id: str, run_id: str) -> str:
    """태스크별 헤더 생성"""
    emoji = TASK_EMOJI_MAP.get(task_id, "📄")
    friendly_name = TASK_FILENAME_MAP.get(task_id, task_id).replace("_", " ").split("_", 1)[-1] if "_" in TASK_FILENAME_MAP.get(task_id, "") else task_id
    
    header = f"""<!--
┌──────────────────────────────────────────────────────────────┐
│ {emoji} Gap Foundry - {friendly_name}
│ Run ID: {run_id}
│ Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
└──────────────────────────────────────────────────────────────┘
-->

"""
    return header


def _generate_report_header(inputs: Dict[str, Any], run_id: str, args) -> str:
    """최종 리포트 메타 정보 헤더 생성"""
    idea = inputs.get("idea_one_liner", "N/A")[:60]
    target = inputs.get("target_customer", "N/A")[:40]
    geo = inputs.get("geo_market", "N/A")
    biz_type = inputs.get("business_type", "N/A")
    
    mode = "Safe Mode" if getattr(args, "safe_mode", False) else "Standard"
    if getattr(args, "auto_revise", False):
        mode += " + Auto-Revise"
    
    header = f"""<!--
╔══════════════════════════════════════════════════════════════════════════════╗
║                        🎯 GAP FOUNDRY - STEP1 REPORT                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  📌 Idea: {idea:<62} ║
║  👥 Target: {target:<60} ║
║  🌍 Market: {geo:<10}  |  💼 Type: {biz_type:<8}  |  ⚙️ Mode: {mode:<15} ║
║  🕐 Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S"):<25}  |  🔖 Run ID: {run_id:<12} ║
╚══════════════════════════════════════════════════════════════════════════════╝
-->

"""
    return header


def _save_task_outputs(
    crew,
    out_dir: Path,
    run_id: str,
    also_save_json_when_possible: bool = True,
) -> Dict[str, str]:
    """
    crew.kickoff() 후 crew.tasks를 순회하면서 각 task.output을 저장.
    TaskOutput은 task.output.raw / task.output.json_dict 등으로 접근 가능.
    """
    outputs_dir = out_dir / "runs" / run_id
    outputs_dir.mkdir(parents=True, exist_ok=True)

    index: Dict[str, str] = {}

    for i, task in enumerate(getattr(crew, "tasks", []) or []):
        task_id = _extract_task_id(task)
        
        # 의미 있는 파일명 생성
        file_stem = _get_friendly_filename(task_id, i + 1)
        raw_path = outputs_dir / f"{file_stem}.md"

        task_output = getattr(task, "output", None)
        if task_output is None:
            _safe_write_text(raw_path, "# (No output)\n")
            index[task_id] = str(raw_path)
            continue

        raw = getattr(task_output, "raw", "") or ""
        
        # 최종 리포트가 아닌 경우 헤더 추가
        if task_id != "final_step1_report":
            header = _generate_task_header(task_id, run_id)
            raw = header + raw
        
        _safe_write_text(raw_path, raw)
        index[task_id] = str(raw_path)

        # 가능하면 JSON도 저장
        if also_save_json_when_possible:
            json_dict = getattr(task_output, "json_dict", None)
            if isinstance(json_dict, dict):
                json_path = outputs_dir / f"{file_stem}.json"
                _safe_write_text(json_path, json.dumps(json_dict, ensure_ascii=False, indent=2))
                index[task_id + "_json"] = str(json_path)

    # 인덱스 파일 저장
    index_path = outputs_dir / "_index.json"
    _safe_write_text(index_path, json.dumps(index, ensure_ascii=False, indent=2))

    return index


def _parse_verdict_from_text(text: str) -> Optional[str]:
    """텍스트에서 VERDICT를 파싱한다."""
    if not text:
        return None
    
    # VERDICT: PASS 또는 VERDICT: FAIL 패턴 찾기
    # 변형 대응: "VERDICT:FAIL", "VERDICT : PASS", "VERDICT: PASS ✅" 등
    match = re.search(r"VERDICT\s*:\s*(PASS|FAIL)", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # **VERDICT: FAIL** 패턴 (마크다운 bold)
    match_bold = re.search(r"\*\*VERDICT\s*:\s*(PASS|FAIL)\*\*", text, re.IGNORECASE)
    if match_bold:
        return match_bold.group(1).upper()
    
    return None


def _extract_verdict_from_crew(crew, out_dir: Optional[Path] = None, run_id: Optional[str] = None) -> Tuple[str, str]:
    """
    Crew 실행 후 red_team_review 또는 red_team_recheck 태스크에서 VERDICT를 추출한다.
    
    Args:
        crew: CrewAI Crew 객체
        out_dir: 출력 디렉토리 (파일에서 fallback 읽기용)
        run_id: 실행 ID (파일에서 fallback 읽기용)
    
    Returns:
        (verdict, raw_output)
        - verdict: "PASS" | "FAIL" | "UNKNOWN"
        - raw_output: red_team 태스크의 전체 출력
    """
    # red_team 태스크 찾기 - 다중 방식으로 안전하게
    red_team_tasks = []
    for task in getattr(crew, "tasks", []) or []:
        # 1) agent role로 찾기 (가장 안전)
        agent = getattr(task, "agent", None)
        agent_role = (getattr(agent, "role", "") or "").lower()
        if "red_team" in agent_role or "레드팀" in agent_role or "반증" in agent_role:
            red_team_tasks.append(task)
            continue
        
        # 2) description 전체에서 찾기 (fallback)
        desc = (getattr(task, "description", "") or "").lower()
        if "red_team" in desc or "공격적으로 검토" in desc or "verdict" in desc:
            red_team_tasks.append(task)
            continue
        
        # 3) task_id 패턴으로 찾기 (마지막 fallback)
        task_id = _extract_task_id(task)
        if "red_team" in task_id.lower():
            red_team_tasks.append(task)
    
    # === 방법 1: task.output에서 직접 가져오기 ===
    if red_team_tasks:
        # 마지막 red_team 태스크 (recheck이 있으면 그걸 사용)
        last_red_team = red_team_tasks[-1]
        task_output = getattr(last_red_team, "output", None)
        
        if task_output is not None:
            raw = getattr(task_output, "raw", "") or str(task_output) or ""
            verdict = _parse_verdict_from_text(raw)
            if verdict:
                return verdict, raw
    
    # === 방법 2: 저장된 파일에서 읽기 (fallback) ===
    if out_dir and run_id:
        run_dir = out_dir / "runs" / run_id
        if run_dir.exists():
            # 레드팀 관련 파일 찾기 (09_레드팀_검토 또는 11_레드팀_재검토)
            red_team_files = []
            for f in sorted(run_dir.glob("*.md")):
                fname_lower = f.name.lower()
                if "레드팀" in fname_lower or "red_team" in fname_lower:
                    red_team_files.append(f)
            
            # 마지막 레드팀 파일에서 VERDICT 파싱
            if red_team_files:
                last_file = red_team_files[-1]
                try:
                    content = last_file.read_text(encoding="utf-8")
                    verdict = _parse_verdict_from_text(content)
                    if verdict:
                        return verdict, content
                except Exception:
                    pass
    
    # === 방법 3: crew의 전체 결과에서 찾기 ===
    # CrewAI의 결과 객체에서 직접 찾기
    crew_result = getattr(crew, "result", None) or getattr(crew, "_result", None)
    if crew_result:
        result_str = str(crew_result)
        verdict = _parse_verdict_from_text(result_str)
        if verdict:
            return verdict, result_str
    
    return "UNKNOWN", ""


def _get_task_output_by_name(crew, task_name_pattern: str) -> str:
    """특정 태스크의 출력을 가져온다."""
    for task in getattr(crew, "tasks", []) or []:
        task_id = _extract_task_id(task)
        if task_name_pattern.lower() in task_id.lower():
            task_output = getattr(task, "output", None)
            if task_output:
                return getattr(task_output, "raw", "") or ""
    return ""


# ============================================================================
# 후속 대화 기능 (리포트에 대한 Q&A)
# ============================================================================

def _start_report_chat(report_text: str, inputs: Dict[str, Any]) -> None:
    """
    리포트 완료 후 사용자와 대화하는 모드.
    사용자가 리포트에 대해 질문하거나 반론(Claim)을 제기하면 LLM이 답변한다.
    """
    try:
        from crewai import LLM
    except ImportError:
        print("⚠️ CrewAI LLM을 불러올 수 없습니다. 대화 모드를 종료합니다.")
        return
    
    # LLM 초기화 (main 모델 사용)
    model = os.getenv("MAIN_LLM_MODEL", "gpt-4.1")
    llm = LLM(model=model)
    
    # 시스템 프롬프트 구성
    idea = inputs.get("idea_one_liner", "N/A")
    target = inputs.get("target_customer", "N/A")
    
    system_prompt = f"""당신은 시장검증 리포트에 대해 토론하는 전문 컨설턴트입니다.

[아이디어 배경]
- 아이디어: {idea}
- 타깃 고객: {target}

[리포트 내용]
{report_text[:8000]}  # 토큰 제한을 위해 앞부분만

[역할]
- 사용자가 리포트에 대해 질문하면 명확하게 답변하세요.
- 사용자가 반론(Claim)을 제기하면:
  1. 먼저 그 관점을 인정하고
  2. 리포트의 근거와 비교 분석하고
  3. 가능하다면 새로운 시각을 제시하세요.
- 사용자의 관점이 타당하면 인정하고, 리포트 결론 수정을 제안할 수도 있습니다.
- 항상 한국어로 답변하세요.
- 답변은 간결하게 (3-5문단 이내).
"""
    
    conversation_history = [{"role": "system", "content": system_prompt}]
    
    print("\n" + "=" * 60)
    print("💬 리포트 후속 대화 모드")
    print("=" * 60)
    print("리포트에 대해 궁금한 점이나 반론이 있으면 자유롭게 말씀하세요.")
    print("종료하려면 'quit', 'exit', 또는 '종료'를 입력하세요.")
    print("=" * 60 + "\n")
    
    while True:
        try:
            user_input = input("📝 나: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n대화를 종료합니다. 감사합니다! 👋")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ["quit", "exit", "q", "종료", "끝", "나가기"]:
            print("\n대화를 종료합니다. 감사합니다! 👋")
            break
        
        # 대화 히스토리에 추가
        conversation_history.append({"role": "user", "content": user_input})
        
        # LLM 호출
        try:
            response = llm.call(messages=conversation_history)
            
            # 응답을 히스토리에 추가
            conversation_history.append({"role": "assistant", "content": response})
            
            print(f"\n🤖 AI: {response}\n")
            
        except Exception as e:
            print(f"\n⚠️ 응답 생성 중 오류: {e}")
            print("   다시 시도해주세요.\n")
            # 실패한 메시지는 히스토리에서 제거
            conversation_history.pop()


def _load_pass1_outputs_for_revision(out_dir: Path, run_id_pass1: str) -> Dict[str, str]:
    """
    Pass1 outputs에서 revision에 필요한 파일들을 읽어온다.
    
    Returns:
        Dict with keys: previous_positioning_output, previous_red_team_output, research_summary
    """
    pass1_dir = out_dir / "runs" / run_id_pass1
    
    def read_md(pattern: str) -> str:
        """패턴이 포함된 md 파일 읽기"""
        for f in pass1_dir.glob("*.md"):
            if pattern.lower() in f.name.lower():
                try:
                    return f.read_text(encoding="utf-8")
                except Exception:
                    continue
        return ""
    
    return {
        "previous_positioning_output": (
            read_md("create_pov") or read_md("positioning") or read_md("pov")
        ),
        "previous_red_team_output": (
            read_md("red_team_review") or read_md("red_team")
        ),
        "research_summary": (
            read_md("summarize") or read_md("summary")
        ),
        "gap_hypotheses": (
            read_md("mine_gaps") or read_md("gap")
        ),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gap Foundry - STEP1 (Competitive Analysis + Idea Refinement) runner"
    )

    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="Path to input JSON file. If omitted, uses CLI args or interactive prompts.",
    )
    parser.add_argument("--idea", type=str, default="", help="One-liner idea")
    parser.add_argument("--target", type=str, default="", help="Target customer")
    parser.add_argument("--problem", type=str, default="", help="Problem statement")
    parser.add_argument(
        "--alternatives",
        type=str,
        default="",
        help="Current alternatives (comma-separated or free text; ideally 3+)",
    )
    parser.add_argument("--geo", type=str, default="KR", help="Geo market (KR/Global)")
    parser.add_argument("--type", type=str, default="B2B", help="Business type (B2B/B2C)")
    parser.add_argument("--constraints", type=str, default="", help="Constraints")
    parser.add_argument("--success", type=str, default="", help="Success definition (STEP1)")

    # 최종 리포트 저장 경로(옵션)
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional final report path (e.g. outputs/step1_report.md). If omitted, prints to stdout.",
    )

    # 태스크별 산출물 저장 디렉토리(기본값: outputs)
    parser.add_argument(
        "--out-dir",
        type=str,
        default="outputs",
        help="Directory to save per-task outputs (default: outputs).",
    )

    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for missing fields interactively.",
    )

    parser.add_argument(
        "--refine",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="LLM 기반 입력 구체화 모드. 아이디어를 자유롭게 설명하면 필요한 정보를 자동 추출/질문. "
             "초기 아이디어를 인자로 전달 가능 (예: --refine '고객 인터뷰 자동 요약 툴')",
    )

    parser.add_argument(
        "--save-refined",
        type=str,
        nargs="?",
        const="inputs/last_refined.json",
        default=None,
        help="--refine 결과를 자동으로 JSON 파일에 저장. "
             "경로 미지정 시 기본값: inputs/last_refined.json",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show configuration without running the crew.",
    )

    parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="red_team이 FAIL 판정 시 자동으로 revision(revise_positioning + red_team_recheck)을 1회 실행. "
             "PASS면 바로 final report로 진행.",
    )
    
    # 운영급 가드레일 옵션
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="운영급 안전 모드: context 크기가 임계치를 넘으면 자동 축소. "
             "TPM 에러 방지를 위한 추가 가드레일 적용.",
    )
    
    # 후속 대화 모드
    parser.add_argument(
        "--chat",
        action="store_true",
        help="리포트 생성 후 후속 대화 모드 시작. "
             "리포트에 대해 질문하거나 반론(Claim)을 제기하면 AI가 답변합니다.",
    )

    args = parser.parse_args(argv)

    inputs: Dict[str, Any] = {}

    # 0) LLM 기반 입력 구체화 모드 (--refine)
    if args.refine is not None:
        initial_idea = args.refine if args.refine else None
        refine_result = refine_inputs(initial_idea)
        
        if not refine_result:
            print("입력 구체화가 취소되었습니다.", file=sys.stderr)
            return 2
        
        inputs = refine_result.get("inputs", {})
        confidence_flags = refine_result.get("confidence_flags", {})
        turns_used = refine_result.get("turns_used", 0)
        
        # 모호한 필드 경고
        ambiguous_fields = [k for k, v in confidence_flags.items() if v == "ambiguous"]
        if ambiguous_fields:
            print(f"⚠️  일부 필드가 모호할 수 있어요: {ambiguous_fields}")
            print("   결과를 해석할 때 참고하세요.\n")
        
        print(f"📊 입력 구체화 완료 (턴 수: {turns_used})\n")
        
        # refine 결과 저장
        save_data = {
            "inputs": inputs,
            "confidence_flags": confidence_flags,
            "turns_used": turns_used,
        }
        
        # --save-refined 옵션이 있으면 자동 저장
        if args.save_refined:
            save_path = Path(args.save_refined)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(
                json.dumps(save_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"💾 자동 저장됨: {save_path}\n")
        else:
            # 수동으로 저장할지 물어봄
            print("💾 입력값을 JSON 파일로 저장하시겠어요? (파일명 입력, 건너뛰려면 Enter)")
            user_save_path = input("   파일명 (예: my_idea.json): ").strip()
            if user_save_path:
                if not user_save_path.endswith(".json"):
                    user_save_path += ".json"
                Path(user_save_path).write_text(
                    json.dumps(save_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                print(f"   ✅ 저장됨: {user_save_path}\n")

    # 1) JSON 파일 입력 (--refine과 병행 가능: refine 결과를 오버라이드)
    if args.input:
        loaded = _load_inputs_from_json(Path(args.input))
        inputs = {**inputs, **loaded}  # refine 결과 위에 JSON 오버라이드

    # 2) CLI args로 오버라이드/보완
    cli_map = {
        "idea_one_liner": args.idea,
        "target_customer": args.target,
        "problem_statement": args.problem,
        "current_alternatives": args.alternatives,
        "geo_market": args.geo,
        "business_type": args.type,
        "constraints": args.constraints,
        "success_definition": args.success,
    }
    for k, v in cli_map.items():
        if v:
            inputs[k] = v

    # 2.5) 선택적 필드에 기본값 적용
    for k, default_val in OPTIONAL_FIELDS.items():
        if not inputs.get(k):
            inputs[k] = default_val

    # 3) 인터랙티브로 누락 채우기
    if args.interactive:
        inputs = _prompt_missing_fields(inputs)

    # 4) 검증
    try:
        _validate_inputs(inputs)
    except Exception as e:
        print(f"❌ Input error: {e}\n", file=sys.stderr)
        print("Tip: Use --refine (LLM 대화형), --interactive, or --input JSON.\n", file=sys.stderr)
        return 2

    # 4.5) revision-only 실행용 기본값 추가 (CrewAI 템플릿 변수 요구 충족)
    # pass1에서는 이 값들이 비어있고, context에서 참조함
    # pass2(revision-only)에서는 pass1 outputs로 채워짐
    inputs.setdefault("previous_positioning_output", "")
    inputs.setdefault("previous_red_team_output", "")
    inputs.setdefault("research_summary", "")
    inputs.setdefault("gap_hypotheses", "")

    # 5) Dry-run 모드
    if args.dry_run:
        print("\n" + "=" * 60)
        print("🔍 DRY-RUN MODE (실행 없이 설정 확인)")
        print("=" * 60)
        print("\n📋 입력값:")
        for k, v in inputs.items():
            print(f"   {k}: {v}")
        print("\n🔧 환경변수:")
        print(f"   SERPER_API_KEY: {'✅ 설정됨' if os.getenv('SERPER_API_KEY') else '❌ 미설정'}")
        print(f"   OPENAI_API_KEY: {'✅ 설정됨' if os.getenv('OPENAI_API_KEY') else '❌ 미설정'}")
        print(f"   MAIN_LLM_MODEL: {os.getenv('MAIN_LLM_MODEL', 'gpt-4.1 (기본값)')}")
        print(f"   FAST_LLM_MODEL: {os.getenv('FAST_LLM_MODEL', 'gpt-4.1-mini (기본값)')}")
        print(f"   NANO_LLM_MODEL: {os.getenv('NANO_LLM_MODEL', 'gpt-4.1-nano (기본값, 미사용)')}")
        print("\n🏗️  Crew 구성 테스트...")
        try:
            crew, tracker = Step1CrewFactory().build(show_progress=False)
            print(f"   ✅ 에이전트 {len(crew.agents)}개 생성됨")
            print(f"   ✅ 태스크 {len(crew.tasks)}개 생성됨")
            print("\n📝 태스크 실행 순서:")
            for i, task in enumerate(crew.tasks, 1):
                agent_role = getattr(task.agent, "role", "unknown")
                print(f"   {i}. {agent_role}")
        except Exception as e:
            print(f"   ❌ Crew 구성 실패: {e}", file=sys.stderr)
            return 1
        print("\n✅ Dry-run 완료. 실제 실행하려면 --dry-run 옵션을 제거하세요.")
        return 0

    # 6) 실행
    out_dir = Path(args.out_dir)
    run_id = _generate_run_id(inputs)

    # --auto-revise: 2-pass 실행 (FAIL이면 revision 후 재실행)
    if args.auto_revise:
        print("\n🔄 Auto-Revise 모드: 1차 실행 시작...")
        
        # === 1차 실행 (revision 없이) ===
        start_time_pass1 = time.time()
        try:
            crew, tracker = Step1CrewFactory().build(include_revision=False)
            if tracker:
                tracker.print_header()
                # 첫 번째 태스크 시작 알림
                if tracker.task_order:
                    tracker.on_task_start(tracker.task_order[0])
            final_result = crew.kickoff(inputs=inputs)
            if tracker:
                tracker.print_summary()
        except Exception as e:
            print(f"❌ Crew execution error (1차): {e}", file=sys.stderr)
            return 1
        elapsed_pass1 = time.time() - start_time_pass1
        
        # 1차 결과 저장 + metrics
        run_id_pass1 = f"{run_id}_pass1"
        try:
            _save_task_outputs(crew, out_dir=out_dir, run_id=run_id_pass1)
            _log_usage_metrics(crew, out_dir=out_dir, run_id=run_id_pass1, elapsed_seconds=elapsed_pass1)
            print(f"\n📁 1차 결과 저장: {out_dir / 'runs' / run_id_pass1}")
        except Exception as e:
            print(f"⚠️ 1차 결과 저장 실패: {e}", file=sys.stderr)
        
        # red_team verdict 확인 (저장된 파일에서도 fallback으로 읽기)
        verdict, _ = _extract_verdict_from_crew(crew, out_dir=out_dir, run_id=run_id_pass1)
        print(f"\n🔍 Red Team Verdict: {verdict}")
        
        # 최종 run_id 추적 (마지막 공통 로직에서 사용)
        final_run_id = run_id_pass1
        metrics_saved = True  # 이미 저장됨
        
        if verdict == "PASS":
            print("✅ PASS! Revision 불필요. 최종 리포트로 진행합니다.")
            final_text = str(final_result)
        
        elif verdict == "FAIL":
            print("❌ FAIL! Revision-only 실행을 시작합니다...\n")
            print("   (revision 태스크 3개만 실행: revise → recheck → report)")
            
            # === Pass1 outputs에서 필요한 데이터 로드 ===
            print("   📂 Pass1 outputs 로딩 중...")
            pass1_outputs = _load_pass1_outputs_for_revision(out_dir, run_id_pass1)
            
            start_time_pass2 = time.time()
            
            if not pass1_outputs.get("previous_positioning_output"):
                print("   ⚠️ Pass1 positioning 결과를 찾을 수 없음. 전체 재실행으로 fallback...")
                # Fallback: 전체 재실행
                crew_v2, tracker_v2 = Step1CrewFactory().build(
                    include_revision=True, show_progress=True
                )
                if tracker_v2:
                    tracker_v2.print_header()
                    if tracker_v2.task_order:
                        tracker_v2.on_task_start(tracker_v2.task_order[0])
                final_result = crew_v2.kickoff(inputs=inputs)
            else:
                # Revision-only 실행: inputs에 pass1 결과 주입
                revision_inputs = {
                    **inputs,
                    **pass1_outputs,  # previous_positioning_output, previous_red_team_output 등
                }
                
                try:
                    crew_v2, tracker_v2 = Step1CrewFactory().build_revision_only(
                        show_progress=True
                    )
                    if tracker_v2:
                        tracker_v2.print_header()
                        if tracker_v2.task_order:
                            tracker_v2.on_task_start(tracker_v2.task_order[0])
                    final_result = crew_v2.kickoff(inputs=revision_inputs)
                    if tracker_v2:
                        tracker_v2.print_summary()
                except Exception as e:
                    print(f"❌ Crew execution error (revision-only): {e}", file=sys.stderr)
                    return 1
            
            elapsed_pass2 = time.time() - start_time_pass2
            
            # 2차 결과 저장 + metrics
            run_id_pass2 = f"{run_id}_pass2_revised"
            try:
                _save_task_outputs(crew_v2, out_dir=out_dir, run_id=run_id_pass2)
                _log_usage_metrics(crew_v2, out_dir=out_dir, run_id=run_id_pass2, elapsed_seconds=elapsed_pass2)
                print(f"\n📁 Revision 결과 저장: {out_dir / 'runs' / run_id_pass2}")
            except Exception as e:
                print(f"⚠️ Revision 결과 저장 실패: {e}", file=sys.stderr)
            
            # 최종 verdict 확인 (red_team_recheck에서 - 파일 fallback 포함)
            verdict_v2, _ = _extract_verdict_from_crew(crew_v2, out_dir=out_dir, run_id=run_id_pass2)
            print(f"\n🔍 Red Team Recheck Verdict: {verdict_v2}")
            if verdict_v2 == "FAIL":
                print("⚠️ Revision 후에도 FAIL입니다. 리포트에 경고가 포함됩니다.")
            
            final_text = str(final_result)
            final_run_id = run_id_pass2
        
        else:  # UNKNOWN
            print("⚠️ VERDICT를 파싱할 수 없습니다. 1차 결과를 최종으로 사용합니다.")
            final_text = str(final_result)
    
    else:
        # --auto-revise 없음: 기본 실행 (revision 없이)
        metrics_saved = False
        
        start_time = time.time()
        try:
            crew, tracker = Step1CrewFactory().build(include_revision=False)
            if tracker:
                tracker.print_header()
                if tracker.task_order:
                    tracker.on_task_start(tracker.task_order[0])
            final_result = crew.kickoff(inputs=inputs)
            if tracker:
                tracker.print_summary()
        except Exception as e:
            print(f"❌ Crew execution error: {e}", file=sys.stderr)
            return 1
        elapsed_time = time.time() - start_time
        
        final_text = str(final_result)
        
        # 태스크별 결과 저장
        try:
            _save_task_outputs(crew, out_dir=out_dir, run_id=run_id)
            print(f"\n✅ Per-task outputs saved under: {out_dir / 'runs' / run_id}")
            print(f"✅ Index: {(out_dir / 'runs' / run_id / '_index.json')}")
        except Exception as e:
            print(f"⚠️ Failed to save per-task outputs: {e}", file=sys.stderr)

    # 7) 토큰 사용량/비용 로깅 (auto-revise에서는 이미 pass별로 저장됨)
    if not args.auto_revise:
        try:
            _log_usage_metrics(crew, out_dir=out_dir, run_id=run_id, elapsed_seconds=elapsed_time)
        except Exception as e:
            print(f"⚠️ Failed to log usage metrics: {e}", file=sys.stderr)

    # 8) 최종 리포트 저장/출력 (메타 정보 헤더 추가)
    report_header = _generate_report_header(inputs, run_id, args)
    final_text_with_header = report_header + final_text
    
    # 리포트 저장 (지정된 경로 또는 reports/ 폴더)
    if args.out:
        out_path = Path(args.out)
    else:
        # 기본: outputs/reports/ 폴더에 저장
        reports_dir = out_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"{run_id}_report.md"
    
    _safe_write_text(out_path, final_text_with_header)
    print(f"\n✅ Final report saved to: {out_path}")

    # 9) 후속 대화 모드 (--chat)
    if args.chat:
        _start_report_chat(final_text, inputs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())