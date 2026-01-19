from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
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
# 운영급 가드레일 #0: PreGate (입력 구체성 체크)
# ============================================================================

# PreGate 규칙 로드 (config/pregate_rules.yaml에서)
def _load_pregate_rules() -> Dict[str, Any]:
    """PreGate 규칙을 YAML 파일에서 로드"""
    rules_path = Path(__file__).parent / "config" / "pregate_rules.yaml"
    
    if rules_path.exists():
        try:
            import yaml
            with open(rules_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    return loaded
        except ImportError:
            print("⚠️ PyYAML 미설치. PreGate 기본 규칙 사용 (pip install pyyaml)", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ pregate_rules.yaml 파싱 실패: {e}. 기본 규칙 사용", file=sys.stderr)
    else:
        # 파일이 없을 때만 경고 (개발 환경에서는 보통 있음)
        print("⚠️ config/pregate_rules.yaml 없음. 기본 규칙 사용", file=sys.stderr)
    
    # 기본값 (yaml 파일이 없거나 로드 실패 시) - 보수적으로 동작
    return {
        "min_lengths": {
            "target_customer": 2,      # 경고용, FAIL 아님
            "problem_statement": 11,
            "idea_one_liner": 15,
            "current_alternatives": 10,
        },
        "specific_short_targets_allowlist": [
            r"^의사$", r"^간호사$", r"^약사$", r"^교사$", r"^개발자$",
            r"^디자이너$", r"^프리랜서$", r"^소상공인$", r"^직장인$",
            r"^doctors?$", r"^nurses?$", r"^developers?$", r"^freelancers?$",
        ],
        "vague_target_patterns": [
            r"^모든\s*사람", r"^누구나", r"^일반인", r"^모두$",
            r"^사람들$", r"^사용자$", r"^고객$",
            r"^everyone$", r"^anyone$", r"^all\s*people",
        ],
        "truism_problem_patterns": [
            # 추상 명사 + 중요/필요 조합만 잡음
            r"(건강|행복|성공|자기계발|시간관리|생산성).*(중요하다|필요하다)$",
            r"좋다$", r"나쁘다$",
            r"(health|happiness|success).*(is\s+important|is\s+needed)$",
        ],
        "action_patterns": {
            "strong": [
                r"자동화", r"계산", r"기록", r"분석", r"추천", r"알림", r"예약", r"매칭",
                r"\bautomate\b", r"\bcalculate\b", r"\btrack\b", r"\banalyze\b",
            ],
            "weak": [
                r"하는", r"해주는", r"돕는", r"만드는", r"관리",
                r"\bhelp\b", r"\bmake\b", r"\breduce\b", r"\bmanage\b",
            ],
        },
        "judgment": {"core_fail_threshold": 2},
    }


# 규칙 캐시 (한 번만 로드)
_PREGATE_RULES: Optional[Dict[str, Any]] = None

def _get_pregate_rules() -> Dict[str, Any]:
    """PreGate 규칙 가져오기 (캐시됨)"""
    global _PREGATE_RULES
    if _PREGATE_RULES is None:
        _PREGATE_RULES = _load_pregate_rules()
    return _PREGATE_RULES


@dataclass
class PreGateResult:
    """PreGate 체크 결과"""
    is_valid: bool
    fail_reasons: list
    warnings: list
    score: float  # 0.0 ~ 1.0 (낮을수록 모호함)


def _pregate_check(data: Dict[str, Any]) -> PreGateResult:
    """
    PreGate: 입력이 랜딩 테스트를 돌릴 만큼 구체적인지 체크.
    
    Q0(Idea Invariance)와 분리:
    - Q0: 아이디어가 '변형'되었는지 체크
    - PreGate: 입력이 '검증 가능한 단위'인지 체크
    
    v2 개선:
    - 짧지만 구체적인 타깃(의사, 개발자) allowlist 지원
    - 길이 기준은 warn으로 (FAIL 아님)
    - action_patterns: strong/weak 2레벨 구조
    - truism_patterns: "추상명사+중요/필요" 조합만 잡음
    
    Returns:
        PreGateResult with:
        - is_valid: PreGate 통과 여부
        - fail_reasons: 실패 이유 목록
        - warnings: 경고 (통과는 했지만 주의 필요)
        - score: 0.0 ~ 1.0 (구체성 점수, 내부용)
    """
    # 규칙 로드
    rules = _get_pregate_rules()
    min_lengths = rules.get("min_lengths", {})
    allowlist = rules.get("specific_short_targets_allowlist", [])
    vague_target_patterns = rules.get("vague_target_patterns", [])
    truism_patterns = rules.get("truism_problem_patterns", [])
    action_patterns = rules.get("action_patterns", {})
    core_fail_threshold = rules.get("judgment", {}).get("core_fail_threshold", 2)
    
    fail_reasons = []
    warnings = []
    checks_passed = 0
    total_checks = 4
    
    target = data.get("target_customer", "").strip()
    target_lower = target.lower()
    problem = data.get("problem_statement", "").strip()
    problem_lower = problem.lower()
    idea = data.get("idea_one_liner", "").strip()
    alternatives = data.get("current_alternatives", "").strip()
    
    # ─────────────────────────────────────────────────────────────
    # Check 1: 타깃이 비특정인가?
    # ─────────────────────────────────────────────────────────────
    is_vague_target = False
    is_in_allowlist = False
    
    # Step 1a: allowlist 체크 (짧아도 구체적인 직군)
    for pattern in allowlist:
        if re.search(pattern, target_lower, re.IGNORECASE):
            is_in_allowlist = True
            break
    
    # Step 1b: vague 패턴 체크 (allowlist보다 우선순위 높음)
    for pattern in vague_target_patterns:
        if re.search(pattern, target_lower, re.IGNORECASE):
            is_vague_target = True
            break
    
    # Step 1c: 길이 체크 (allowlist에 없고 vague도 아닐 때만 warn)
    min_target_len = min_lengths.get("target_customer", 2)
    if not is_in_allowlist and not is_vague_target and len(target) < min_target_len:
        warnings.append(f"타깃이 짧음 (권장: 더 구체적으로): '{target}'")
    
    if is_vague_target:
        fail_reasons.append(f"타깃이 비특정: '{target}'")
    else:
        checks_passed += 1
    
    # ─────────────────────────────────────────────────────────────
    # Check 2: 문제가 상식 수준인가?
    # ─────────────────────────────────────────────────────────────
    is_truism = False
    for pattern in truism_patterns:
        if re.search(pattern, problem_lower, re.IGNORECASE):
            is_truism = True
            break
    
    # 길이 체크: 너무 짧으면 warn (FAIL 아님)
    min_problem_len = min_lengths.get("problem_statement", 11)
    if len(problem) < min_problem_len and not is_truism:
        warnings.append(f"문제 설명이 짧음 (권장: 더 구체적으로): '{problem}'")
    
    if is_truism:
        fail_reasons.append(f"문제가 상식 수준: '{problem}'")
    else:
        checks_passed += 1
    
    # ─────────────────────────────────────────────────────────────
    # Check 3: 아이디어가 행동을 포함하는가? (strong/weak 2레벨)
    # ─────────────────────────────────────────────────────────────
    has_strong_action = False
    has_weak_action = False
    
    # action_patterns가 dict(새 구조)인지 list(구 구조)인지 확인
    if isinstance(action_patterns, dict):
        strong_patterns = action_patterns.get("strong", [])
        weak_patterns = action_patterns.get("weak", [])
    else:
        # 구 구조 호환: 전부 strong으로 취급
        strong_patterns = action_patterns
        weak_patterns = []
    
    # strong 패턴 체크
    for pattern in strong_patterns:
        if re.search(pattern, idea, re.IGNORECASE):
            has_strong_action = True
            break
    
    # weak 패턴 체크 (strong이 없을 때만)
    if not has_strong_action:
        for pattern in weak_patterns:
            if re.search(pattern, idea, re.IGNORECASE):
                has_weak_action = True
                break
    
    # 아이디어 길이 체크
    min_idea_len = min_lengths.get("idea_one_liner", 15)
    if len(idea) < min_idea_len:
        warnings.append(f"아이디어가 짧음 (권장: 더 구체적으로): '{idea}'")
    
    # 판정: strong 있으면 PASS, weak만 있으면 warn + PASS, 둘 다 없으면 FAIL
    if has_strong_action:
        checks_passed += 1
    elif has_weak_action:
        # weak만 있으면 warn 추가하지만 PASS는 시킴
        warnings.append(f"행동이 범용적 (권장: 더 구체적인 행동으로): '{idea}'")
        checks_passed += 1
    else:
        fail_reasons.append(f"아이디어에 구체적 행동이 없음: '{idea}'")
    
    # ─────────────────────────────────────────────────────────────
    # Check 4: 현재 대안이 있는가? (경고만, 실패 아님)
    # ─────────────────────────────────────────────────────────────
    min_alt_len = min_lengths.get("current_alternatives", 10)
    if not alternatives or len(alternatives) < min_alt_len:
        warnings.append("현재 대안이 명시되지 않음")
    else:
        checks_passed += 1
    
    # 점수 계산 (0.0 ~ 1.0, 내부 디버깅용)
    score = checks_passed / total_checks
    
    # 판정: 핵심 3개 중 threshold 이상 실패하면 PreGate FAIL
    core_fails = len([r for r in fail_reasons if "타깃" in r or "문제" in r or "행동" in r])
    is_valid = core_fails < core_fail_threshold
    
    return PreGateResult(
        is_valid=is_valid,
        fail_reasons=fail_reasons,
        warnings=warnings,
        score=score,
    )


def _generate_pregate_fail_report(
    inputs: Dict[str, Any],
    pregate_result: PreGateResult,
    out_dir: Path,
    run_id: str,
) -> str:
    """
    PreGate FAIL 시 생성되는 리포트.
    사용자에게 무엇이 부족한지, 어떻게 수정하면 좋을지 안내.
    """
    report_lines = [
        "<!--",
        "╔══════════════════════════════════════════════════════════════════════════════╗",
        "║                        🎯 GAP FOUNDRY - STEP1 REPORT                         ║",
        "╠══════════════════════════════════════════════════════════════════════════════╣",
        f"║  📌 Idea: {inputs.get('idea_one_liner', 'N/A')[:60]:<60} ║",
        f"║  👥 Target: {inputs.get('target_customer', 'N/A')[:58]:<58} ║",
        f"║  🕐 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}        |  🔖 Run ID: {run_id[:30]} ║",
        "╚══════════════════════════════════════════════════════════════════════════════╝",
        "-->",
        "",
        "## 🚦 Validation Gate 결과 요약",
        "",
        "### 최종 판정",
        "**🔴 LANDING_NO**",
        "",
        "**사유**: 검증 단위 성립 불가 (모호함/상식 수준)",
        "",
        "---",
        "",
        "## ❌ PreGate 실패: 초기 검증을 시도하기에 입력이 너무 모호합니다",
        "",
        "시장 검증(Landing Test, PoC, Interview 등)을 실행하려면 **구체적인 검증 단위**가 필요합니다.",
        "현재 입력은 너무 추상적이어서 경쟁 분석이나 초기 실험을 의미 있게 수행할 수 없습니다.",
        "",
        "---",
        "",
        "## 🔍 부족한 부분",
        "",
    ]
    
    for i, reason in enumerate(pregate_result.fail_reasons, 1):
        report_lines.append(f"### {i}. {reason.split(':')[0]}")
        report_lines.append(reason)
        report_lines.append("")
    
    if pregate_result.warnings:
        report_lines.append("## ⚠️ 경고 (권장 수정)")
        report_lines.append("")
        for warning in pregate_result.warnings:
            report_lines.append(f"- {warning}")
        report_lines.append("")
    
    # 사용자 입력 기반 리라이트 예시 생성
    user_idea = inputs.get('idea_one_liner', '건강 앱')
    user_target = inputs.get('target_customer', '모든 사람')
    
    report_lines.extend([
        "---",
        "",
        "## 🔧 이렇게 고쳐보세요",
        "",
        "### ❌ 현재 입력 (너무 추상적)",
        f"- 아이디어: {user_idea}",
        f"- 타깃: {user_target}",
        f"- 문제: {inputs.get('problem_statement', '')}",
        "",
        "### ✅ 리라이트 예시",
        "",
        "**예시 1**: 야근 많은 30대 직장인이 저녁 10시 이후 과식을 줄이게 돕는 앱",
        "- 타깃: 주 3회 이상 야근하는 30대 사무직",
        "- 문제: 늦은 퇴근 후 스트레스 해소로 과식 → 체중 증가 → 다음날 후회 반복",
        "",
        "**예시 2**: 프리랜서 개발자를 위한 세금 자동 계산 및 신고 대행 서비스",
        "- 타깃: 연 매출 1억 미만의 1인 프리랜서 개발자",
        "- 문제: 매년 5월 종합소득세 신고 시 경비 처리가 복잡해서 세무사에게 30-50만원을 내거나 직접 밤새 씨름한다",
        "",
        "---",
        "",
        "### 다음 단계",
        "",
        "`--refine` 옵션으로 대화형 입력 구체화를 사용해보세요:",
        "```bash",
        "python3 -m gap_foundry.main --refine",
        "```",
        "",
        "---",
        "*Generated by [Gap Foundry](https://github.com/utopify/gap_foundry) - AI-powered Market Validation*",
    ])
    
    return "\n".join(report_lines)


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


def _generate_report_header(
    inputs: Dict[str, Any], 
    run_id: str, 
    args,
    run_started_at: str = "",
    run_finished_at: str = "",
    total_elapsed: float = 0,
    stage_times: Optional[Dict[str, float]] = None,
    final_verdict: str = ""
) -> str:
    """최종 리포트 메타 정보 헤더 + 실행 정보 + Idea Anchor 생성 (코드가 정확한 시간 삽입)"""
    idea = inputs.get("idea_one_liner", "N/A")
    target = inputs.get("target_customer", "N/A")
    problem = inputs.get("problem_statement", "N/A")
    geo = inputs.get("geo_market", "N/A")
    biz_type = inputs.get("business_type", "N/A")
    
    mode = "Safe Mode" if getattr(args, "safe_mode", False) else "Standard"
    if getattr(args, "auto_revise", False):
        mode += " + Auto-Revise"
    
    # Verdict 이모지
    verdict_emoji = "🟢" if final_verdict == "LANDING_GO" else "🟡" if final_verdict == "LANDING_HOLD" else "🔴" if final_verdict == "LANDING_NO" else "⚪"
    verdict_msg = "시장 검증 시도 가치 충분" if final_verdict == "LANDING_GO" else "실험 설계 보완 필요" if final_verdict == "LANDING_HOLD" else "입력 구체화/재검토 권장"
    
    # ═══════════════════════════════════════════════════════════════
    # 실행 시간 포맷팅 (SSOT: Single Source of Truth)
    # ═══════════════════════════════════════════════════════════════
    if total_elapsed > 0:
        mins = int(total_elapsed // 60)
        secs = int(total_elapsed % 60)
        elapsed_str = f"{mins}분 {secs}초 ({total_elapsed:.1f}초)"
    else:
        elapsed_str = "N/A"
    
    # Stage별 시간 문자열
    stage_times_str = ""
    if stage_times:
        for stage_name, stage_sec in stage_times.items():
            stage_mins = int(stage_sec // 60)
            stage_secs = int(stage_sec % 60)
            stage_times_str += f"  - {stage_name}: {stage_mins}분 {stage_secs}초\n"
    else:
        stage_times_str = "  - N/A\n"
    
    header = f"""<!--
╔══════════════════════════════════════════════════════════════════════════════╗
║                        🎯 GAP FOUNDRY - STEP1 REPORT                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  📌 Idea: {idea[:60]:<62} ║
║  👥 Target: {target[:55]:<60} ║
║  🌍 Market: {geo:<10}  |  💼 Type: {biz_type:<8}  |  ⚙️ Mode: {mode:<15} ║
║  🕐 Generated: {run_finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"):<25}  |  🔖 Run ID: {run_id:<12} ║
╚══════════════════════════════════════════════════════════════════════════════╝
-->

## 🧩 검증 대상 아이디어 (Idea Anchor)

- **아이디어 원문**  
  → {idea}

- **해결하려는 문제**  
  → {problem}

- **타깃 고객**  
  → {target}

- **의도한 핵심 행동**  
  → {inputs.get("current_alternatives", "대안 없음")}을 대체하여 이 서비스를 사용

※ **아래 모든 판단은 이 아이디어를 변형하지 않고 그대로 유지한 상태에서 이루어졌습니다.**

---

## 🚦 Validation Gate 결과 요약

### 최종 판정
**{verdict_emoji} {final_verdict or "판정 대기"}: {verdict_msg}**

---

"""
    return header


def _generate_report_footer(
    metrics: Dict[str, Any],
    run_started_at: str = "",
    run_finished_at: str = "",
    total_elapsed: float = 0,
    stage_times: Optional[Dict[str, float]] = None,
) -> str:
    """리포트 푸터 생성 (실행 정보 + 토큰/비용 - 맨 마지막에 표시)"""
    tokens = metrics.get("tokens", {})
    total_tokens = tokens.get("total_tokens", 0)
    prompt_tokens = tokens.get("prompt_tokens", 0)
    completion_tokens = tokens.get("completion_tokens", 0)
    requests = tokens.get("successful_requests", 0)
    cost = metrics.get("estimated_cost_usd", 0)
    
    # 실행 시간 포맷팅
    if total_elapsed > 0:
        mins = int(total_elapsed // 60)
        secs = int(total_elapsed % 60)
        elapsed_str = f"{mins}분 {secs}초 ({total_elapsed:.1f}초)"
    else:
        elapsed_str = "N/A"
    
    # Stage별 시간 문자열
    stage_times_str = ""
    if stage_times:
        for stage_name, stage_sec in stage_times.items():
            stage_mins = int(stage_sec // 60)
            stage_secs = int(stage_sec % 60)
            stage_times_str += f"  - {stage_name}: {stage_mins}분 {stage_secs}초\n"
    else:
        stage_times_str = "  - N/A\n"
    
    footer = f"""

---

## 📊 실행 정보 & 비용

### ⏱️ 실행 시간
- **총 실행 시간**: {elapsed_str}
- **실행 시작**: {run_started_at or "N/A"}
- **실행 종료**: {run_finished_at or "N/A"}
- **포함 단계**:
{stage_times_str}
### 💰 토큰/비용 통계

| 항목 | 값 |
|------|-----|
| 📝 총 토큰 | {total_tokens:,} |
| 📥 입력 토큰 | {prompt_tokens:,} |
| 📤 출력 토큰 | {completion_tokens:,} |
| 🔄 API 요청 | {requests:,}회 |
| 💰 추정 비용 | **${cost:.4f} USD** |

---
*Generated by [Gap Foundry](https://github.com/utopify/gap_foundry) - AI-powered Market Validation*
"""
    return footer


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
    """
    텍스트에서 VERDICT를 파싱한다.
    
    신규 시장검증 게이트 판정 체계:
    - VALIDATION_GO (또는 LANDING_GO): 초기 검증 시도 가치 충분
    - VALIDATION_HOLD (또는 LANDING_HOLD): 실험 설계 보완 필요
    - VALIDATION_NO (또는 LANDING_NO): 검증 단위 미성립
    
    (내부 로직은 LANDING_* 포맷으로 통일하여 처리)
    
    ⚠️ word boundary (\b) 사용으로 부분 매칭 방지
    """
    if not text:
        return None
    
    # 1) 신규 포맷 우선 (word boundary로 정확한 매칭)
    m = re.search(
        r"VERDICT\s*:\s*(LANDING_GO|LANDING_HOLD|LANDING_NO|VALIDATION_GO|VALIDATION_HOLD|VALIDATION_NO)\b",
        text,
        re.IGNORECASE
    )
    if m:
        verdict = m.group(1).upper()
        # 내부 로직 호환을 위해 VALIDATION -> LANDING 변환
        return verdict.replace("VALIDATION_", "LANDING_")
    
    # 2) 레거시 포맷 fallback (PASS → GO, FAIL → NO)
    m2 = re.search(r"VERDICT\s*:\s*(PASS|FAIL)\b", text, re.IGNORECASE)
    if m2:
        legacy = m2.group(1).upper()
        return "LANDING_GO" if legacy == "PASS" else "LANDING_NO"
    
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
        - verdict: "LANDING_GO" | "LANDING_HOLD" | "LANDING_NO" | "UNKNOWN"
                   (레거시 PASS → LANDING_GO, FAIL → LANDING_NO로 자동 변환)
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
        help="Path to input JSON file. If omitted, uses CLI args.",
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
        "--dry-run",
        action="store_true",
        help="Validate inputs and show configuration without running the crew.",
    )

    parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Landing Gate 판정이 LANDING_HOLD일 때 자동으로 revision을 1회 실행. "
             "LANDING_GO면 바로 final report, LANDING_NO면 revision 없이 종료.",
    )
    parser.add_argument(
        "--revise-no",
        action="store_true",
        help="--auto-revise와 함께 사용. LANDING_NO일 때도 revision을 시도. "
             "(기본적으로 NO는 revision 없이 종료됨)",
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

    # 1) JSON 파일 입력
    if args.input:
        loaded = _load_inputs_from_json(Path(args.input))
        inputs = {**inputs, **loaded}

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

    # 3) 검증
    try:
        _validate_inputs(inputs)
    except Exception as e:
        print(f"❌ Input error: {e}\n", file=sys.stderr)
        return 2

    # 4) 엔진 실행
    try:
        return run_gap_foundry_engine(inputs, args)
    except Exception as e:
        print(f"❌ Execution error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def run_gap_foundry_engine(
    inputs: Dict[str, Any], 
    args: argparse.Namespace, 
    custom_run_id: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
) -> int:
    """
    Gap Foundry 핵심 엔진 (JSON/Dict 입력을 받아 리포트 생성)
    
    Args:
        inputs: 아이디어 입력 데이터
        args: 실행 옵션
        custom_run_id: 커스텀 실행 ID (웹 API용)
        progress_callback: 진행 상태 업데이트 콜백 (task_id, status, progress, step)
    """
    # 1) PreGate: 입력 구체성 체크
    pregate_result = _pregate_check(inputs)
    
    if not pregate_result.is_valid:
        print("\n" + "=" * 60)
        print("🔴 LANDING_NO: 검증 단위 성립 불가 (모호함/상식 수준)")
        print("=" * 60)
        print("\n❌ 실패 항목:")
        for reason in pregate_result.fail_reasons:
            first_line = reason.split('\n')[0]
            print(f"   • {first_line}")
        
        # PreGate FAIL 리포트 생성 및 저장
        out_dir = Path(args.out_dir)
        run_id = custom_run_id or _generate_run_id(inputs)
        fail_report = _generate_pregate_fail_report(inputs, pregate_result, out_dir, run_id)
        
        report_dir = out_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        idea_slug = re.sub(r"[^\w가-힣]", "", inputs.get("idea_one_liner", "unknown"))[:15]
        biz_type = inputs.get("business_type", "B2C")
        report_filename = f"{datetime.now().strftime('%Y-%m-%d_%H%M')}_{idea_slug}_{biz_type}_report.md"
        report_path = report_dir / report_filename
        report_path.write_text(fail_report, encoding="utf-8")
        
        print(f"\n📁 리포트 저장: {report_path}")
        print("=" * 60)
        return 3  # PreGate FAIL exit code
    
    # 2) 2-stage 실행 및 revision-only용 기본값 추가
    inputs.setdefault("previous_positioning_output", "")
    inputs.setdefault("previous_red_team_output", "")
    inputs.setdefault("research_summary", "")
    inputs.setdefault("gap_hypotheses", "")
    inputs.setdefault("landing_gate_verdict", "")

    # 3) Dry-run 모드
    if args.dry_run:
        print("\n" + "=" * 60)
        print("🔍 DRY-RUN MODE")
        print("=" * 60)
        try:
            crew, tracker = Step1CrewFactory().build(show_progress=False)
            print(f"   ✅ 에이전트 {len(crew.agents)}개 생성됨")
            print(f"   ✅ 태스크 {len(crew.tasks)}개 생성됨")
            return 0
        except Exception as e:
            print(f"   ❌ Crew 구성 실패: {e}", file=sys.stderr)
            return 1

    # 4) 실행 준비
    out_dir = Path(args.out_dir)
    run_id = custom_run_id or _generate_run_id(inputs)
    run_started_at = time.time()
    run_started_at_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stage_times: Dict[str, float] = {}
    
    final_verdict: str = ""
    final_text: str = ""

    # 5) 메인 워크플로우 (Auto-Revise 또는 Standard)
    if args.auto_revise:
        # Pass 1: 리서치 + 판정
        print("\n🔍 Pass 1: 리서치 + Landing Gate 판정...")
        start_time_pass1 = time.time()
        crew_pass1, tracker = Step1CrewFactory().build_without_final_report(
            include_revision=False, show_progress=True, external_callback=progress_callback
        )
        pass1_result = crew_pass1.kickoff(inputs=inputs)
        elapsed_pass1 = time.time() - start_time_pass1
        stage_times["Pass 1 (Research + Gate)"] = elapsed_pass1
        
        run_id_pass1 = f"{run_id}_pass1"
        _save_task_outputs(crew_pass1, out_dir=out_dir, run_id=run_id_pass1)
        _log_usage_metrics(crew_pass1, out_dir=out_dir, run_id=run_id_pass1, elapsed_seconds=elapsed_pass1)
        
        verdict, _ = _extract_verdict_from_crew(crew_pass1, out_dir=out_dir, run_id=run_id_pass1)
        final_verdict = verdict
        final_stage_run_id = run_id_pass1
        
        # Pass 2: Revision (필요시)
        do_revision = (verdict == "LANDING_HOLD") or (verdict == "LANDING_NO" and args.revise_no)
        if do_revision:
            print(f"\n🔧 Pass 2: Revision ({verdict})...")
            pass1_outputs = _load_pass1_outputs_for_revision(out_dir, run_id_pass1)
            revision_inputs = {**inputs, **pass1_outputs}
            
            start_time_pass2 = time.time()
            crew_pass2, _ = Step1CrewFactory().build_revision_only(show_progress=True, external_callback=progress_callback)
            pass2_result = crew_pass2.kickoff(inputs=revision_inputs)
            elapsed_pass2 = time.time() - start_time_pass2
            stage_times["Pass 2 (Revision)"] = elapsed_pass2
            
            run_id_pass2 = f"{run_id}_pass2"
            _save_task_outputs(crew_pass2, out_dir=out_dir, run_id=run_id_pass2)
            _log_usage_metrics(crew_pass2, out_dir=out_dir, run_id=run_id_pass2, elapsed_seconds=elapsed_pass2)
            
            verdict_v2, _ = _extract_verdict_from_crew(crew_pass2, out_dir=out_dir, run_id=run_id_pass2)
            final_verdict = verdict_v2 if verdict_v2 else verdict
            final_stage_run_id = run_id_pass2

        # Stage B: 리포트 생성
        print("\n📝 Stage B: 최종 리포트 생성...")
        stage_outputs = _load_pass1_outputs_for_revision(out_dir, final_stage_run_id)
        report_inputs = {
            **inputs,
            "landing_gate_verdict": final_verdict,
            **stage_outputs
        }
        start_time_report = time.time()
        crew_report, _ = Step1CrewFactory().build_final_report_only(show_progress=True)
        final_result = crew_report.kickoff(inputs=report_inputs)
        elapsed_report = time.time() - start_time_report
        stage_times["Stage B (Report)"] = elapsed_report
        final_text = str(final_result)
        final_run_id = f"{run_id}_final"
        _save_task_outputs(crew_report, out_dir=out_dir, run_id=final_run_id)
        _log_usage_metrics(crew_report, out_dir=out_dir, run_id=final_run_id, elapsed_seconds=elapsed_report)
    
    else:
        # Standard 2-stage
        print("\n🚀 Stage 1: 리서치 + Landing Gate 판정...")
        start_time = time.time()
        crew_stage1, _ = Step1CrewFactory().build_without_final_report(include_revision=False, show_progress=True)
        stage1_result = crew_stage1.kickoff(inputs=inputs)
        elapsed_time = time.time() - start_time
        stage_times["Stage 1 (Research + Gate)"] = elapsed_time
        
        stage1_run_id = f"{run_id}_stage1"
        _save_task_outputs(crew_stage1, out_dir=out_dir, run_id=stage1_run_id)
        
        verdict, _ = _extract_verdict_from_crew(crew_stage1, out_dir=out_dir, run_id=stage1_run_id)
        final_verdict = verdict
        
        print("\n📝 Stage 2: 최종 리포트 생성...")
        stage1_outputs = _load_pass1_outputs_for_revision(out_dir, stage1_run_id)
        report_inputs = {
            **inputs,
            "landing_gate_verdict": verdict,
            "research_summary": stage1_outputs.get("research_summary", ""),
            "gap_hypotheses": stage1_outputs.get("gap_hypotheses", ""),
        }
        crew_stage2, _ = Step1CrewFactory().build_final_report_only(show_progress=True)
        final_result = crew_stage2.kickoff(inputs=report_inputs)
        final_text = str(final_result)
        _save_task_outputs(crew_stage2, out_dir=out_dir, run_id=run_id)

    # 6) 결과 정리 및 저장
    total_elapsed = time.time() - run_started_at
    run_finished_at_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Metrics 로드 (마지막 실행 단계 기준)
    metrics = {}
    try:
        final_metrics_run_id = f"{run_id}_final" if args.auto_revise else run_id
        metrics_path = out_dir / "runs" / final_metrics_run_id / "_usage_metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception: pass

    report_header = _generate_report_header(
        inputs=inputs, run_id=run_id, args=args,
        run_started_at=run_started_at_iso, run_finished_at=run_finished_at_iso,
        total_elapsed=total_elapsed, stage_times=stage_times, final_verdict=final_verdict
    )
    report_footer = _generate_report_footer(
        metrics=metrics,
        run_started_at=run_started_at_iso,
        run_finished_at=run_finished_at_iso,
        total_elapsed=total_elapsed,
        stage_times=stage_times,
    ) if metrics else ""
    
    # 본문 클리닝 (중복 섹션 제거 등)
    code_only_headers = [
        r'##\s*⏱️\s*실행\s*정보.*?(?=\n##|\n---|\Z)',
        r'##\s*🧩\s*검증\s*대상\s*아이디어.*?(?=\n##|\n---|\Z)',
        r'##\s*🚦\s*Landing\s*Gate\s*결과\s*요약.*?(?=\n##|\n---|\Z)',
        r'##\s*📊\s*토큰/비용\s*통계.*?(?=\n##|\n---|\Z)',
    ]
    for pattern in code_only_headers:
        final_text = re.sub(pattern, '', final_text, flags=re.DOTALL)
    
    final_report = report_header + final_text + report_footer
    
    if args.out:
        out_path = Path(args.out)
    else:
        reports_dir = out_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"{run_id}_report.md"
    
    _safe_write_text(out_path, final_report)
    print(f"\n✅ Final report saved: {out_path}")

    # 후속 대화 모드
    if args.chat:
        _start_report_chat(final_text, inputs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())