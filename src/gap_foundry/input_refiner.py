"""
입력 구체화 모듈 (Input Refiner) - Interview Style

핵심 철학:
- "폼을 채우는 봇"이 아니라 "아이디어를 이해하려는 동료"
- 질문이 아니라 "해석 제안"
- 종료 시점은 사용자가 결정

2-Phase 구조:
- Phase A (Exploration): 아이디어 이해 중심, 맥락/감정/계기 탐색
- Phase B (Structuring): 이해한 내용을 구조화, 확인/보완

사용법:
    from gap_foundry.input_refiner import refine_inputs
    result = refine_inputs()
    inputs = result["inputs"]
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

from crewai import LLM


# ============================================================================
# 설정
# ============================================================================

DEFAULT_FAST_MODEL = "gpt-4.1-mini"
DEFAULT_MAIN_MODEL = "gpt-4.1"

# 최종 OUTPUT에 필요한 필드 (내부용, 사용자에게 노출 안 함)
# Note: constraints, success_definition은 시장 검증 핵심이 아니므로 제외
REQUIRED_FIELDS = [
    "idea_one_liner",
    "target_customer",
    "problem_statement",
    "current_alternatives",
    "geo_market",
    "business_type",
]

# 필드별 기본값 (마지막에 누락된 경우)
DEFAULT_VALUES = {
    "geo_market": "KR",
    "business_type": "B2C",
}


# ============================================================================
# 능동적 호기심 질문 생성 프롬프트
# ============================================================================

CURIOSITY_PROMPT = """현재 아이디어 이해 상태를 보고,
다음 중 가장 중요한 '하나'를 더 이해하기 위한 질문 의도를 고르세요.

우선순위:
1. 왜 이 문제가 생겼는지 (계기/경험)
2. 실제로 가장 불편한 순간 (행동/상황)
3. 이 문제를 가장 절실히 느끼는 사람
4. 지금 쓰는 대안의 구체적 불만
5. 왜 지금 이 문제인지 (타이밍)

출력 형식 (JSON만, 다른 텍스트 금지):
- focus: 선택한 우선순위 항목
- intent: 이걸 더 이해하면 전체 아이디어가 명확해지는 이유 (1문장)
- suggested_angle: 해석 제안 형태의 질문 방향 (자연어, 물음표 금지)"""


# ============================================================================
# Phase A: Exploration (이해 중심) 프롬프트
# ============================================================================

EXPLORATION_PROMPT = """당신은 창업 아이디어를 이해하려는 동료입니다.
평가하거나 판단하지 말고, 먼저 이해하세요.

[당신의 역할]
- 사용자의 아이디어를 "이해"하려고 노력합니다
- 체크리스트를 채우려 하지 않습니다
- 자연스러운 대화를 합니다
- 질문보다는 "해석 제안"을 합니다

[탐색할 것들] (순서/완성도 강제 X)
- 왜 이 아이디어가 떠올랐는지 (계기, 경험)
- 어떤 상황에서 이 문제가 발생하는지
- 누가 이 문제를 가장 크게 느끼는지
- 지금은 어떻게 해결하고 있는지
- 감정: 짜증, 시간 낭비, 불안 등

[대화 스타일]
- 친근하고 호기심 어린 톤
- 한 번에 1~2가지만 물어보기
- "~인 것 같아요. 맞나요?" 형태로 해석 제안
- 이모지 적당히 사용 OK

[절대 하지 말 것]
- JSON 출력
- "타깃 고객이 누구인가요?" 같은 직접적 필드 질문
- 체크리스트 언급
- 평가/판단

[현재까지 이해한 내용]
{current_understanding}

[대화 기록]
{conversation_summary}

사용자의 마지막 말에 자연스럽게 응답하세요."""


# ============================================================================
# Phase B: Structuring (구조화) 프롬프트
# ============================================================================

STRUCTURING_PROMPT = """당신은 사용자와 대화하며 아이디어를 이해한 동료입니다.
이제 이해한 내용을 정리해서 확인받을 차례입니다.

[현재까지 이해한 내용]
{current_understanding}

[아직 명확하지 않은 부분]
{unclear_parts}

[당신의 역할]
1. 이해한 내용을 자연스럽게 요약해서 보여주기
2. 명확하지 않은 부분은 "추정"으로 표시하고, 맞는지 물어보기
3. 사용자가 OK하면 → 시장 검증 진행 제안

[응답 형식]
자연어로 응답하세요. JSON 출력하지 마세요.

예시:
"지금까지 이야기 정리해볼게요 📋

**아이디어**: ...
**이 문제를 가장 크게 느끼는 사람**: ...
**핵심 불편함**: ...
**지금 대안**: ... (추정)

이 정도면 시장 검증을 시작할 수 있어요!
혹시 수정하고 싶은 부분이 있으면 말씀해주세요.
괜찮으면 'done' 또는 '시작'이라고 해주세요 😊"

[대화 기록]
{conversation_summary}"""


# ============================================================================
# 내부 상태 추출 프롬프트 (사용자에게 노출 안 됨)
# ============================================================================

EXTRACTION_PROMPT = """대화 내용을 분석해서 시장검증에 필요한 정보를 추출하세요.

[추출 규칙]
- 확실한 정보만 추출
- 추정인 경우 "confidence": "low"로 표시
- 언급되지 않은 필드는 null

반드시 아래 JSON 형식으로만 응답하세요:
- idea_one_liner: 아이디어 한 문장 요약 또는 null
- target_customer: 타깃 고객 또는 null
- problem_statement: 해결하려는 문제 또는 null
- current_alternatives: 현재 대안들 또는 null
- geo_market: KR/US/Global 또는 null
- business_type: B2B/B2C/B2B2C 또는 null
- confidence: 각 필드별 high/medium/low
- raw_understanding: 전체적인 아이디어 이해 요약 (2~3문장)"""


# ============================================================================
# 데이터 클래스
# ============================================================================

@dataclass
class RefinerState:
    """인터뷰어의 내부 상태"""
    raw_understanding: str = ""  # 자유 텍스트 요약
    hypotheses: Dict[str, Any] = field(default_factory=dict)  # 추정한 필드
    confidence: Dict[str, str] = field(default_factory=dict)  # 확신 수준
    phase: str = "exploration"  # exploration / structuring
    turn_count: int = 0
    exploration_done: bool = False


@dataclass
class RefinerResult:
    """입력 구체화 결과"""
    inputs: Dict[str, Any] = field(default_factory=dict)
    transcript: List[Dict[str, str]] = field(default_factory=list)
    confidence_flags: Dict[str, str] = field(default_factory=dict)
    is_confirmed: bool = False
    turns_used: int = 0


# ============================================================================
# 헬퍼 함수
# ============================================================================

def _get_llm(model_type: str = "fast") -> LLM:
    """LLM 인스턴스 생성"""
    if model_type == "main":
        model = os.getenv("MAIN_LLM_MODEL", DEFAULT_MAIN_MODEL)
    else:
        model = os.getenv("REFINER_LLM_MODEL") or os.getenv("FAST_LLM_MODEL", DEFAULT_FAST_MODEL)
    return LLM(model=model)


def _extract_json_from_response(response: str) -> Optional[Dict[str, Any]]:
    """응답에서 JSON 추출"""
    if not response:
        return None
    
    # ```json ... ``` 패턴
    match = re.search(r"```json\s*([\s\S]*?)\s*```", response, re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # 전체가 JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass
    
    # { ... } 추출
    first = response.find("{")
    last = response.rfind("}")
    if 0 <= first < last:
        try:
            return json.loads(response[first:last + 1])
        except json.JSONDecodeError:
            pass
    
    return None


def _format_understanding(state: RefinerState) -> str:
    """현재 이해 상태를 포맷팅"""
    if not state.hypotheses:
        return "(아직 이해한 내용 없음)"
    
    lines = []
    field_labels = {
        "idea_one_liner": "아이디어",
        "target_customer": "타깃",
        "problem_statement": "문제",
        "current_alternatives": "현재 대안",
        "geo_market": "시장",
        "business_type": "비즈니스 유형",
    }
    
    for key, label in field_labels.items():
        value = state.hypotheses.get(key)
        if value:
            conf = state.confidence.get(key, "medium")
            marker = "✓" if conf == "high" else "?" if conf == "low" else "~"
            lines.append(f"[{marker}] {label}: {value}")
    
    if state.raw_understanding:
        lines.insert(0, f"📝 요약: {state.raw_understanding}\n")
    
    return "\n".join(lines) if lines else "(아직 이해한 내용 없음)"


def _get_unclear_parts(state: RefinerState) -> str:
    """명확하지 않은 부분 목록"""
    unclear = []
    
    for key in REQUIRED_FIELDS:
        value = state.hypotheses.get(key)
        conf = state.confidence.get(key, "low")
        
        if not value:
            unclear.append(f"- {key}: 아직 파악 안 됨")
        elif conf == "low":
            unclear.append(f"- {key}: 추정 ({value})")
    
    return "\n".join(unclear) if unclear else "모든 항목이 충분히 파악됨"


def _should_transition_to_structuring(state: RefinerState) -> bool:
    """구조화 단계로 전환할지 판단"""
    # 최소 3턴 이상 + 핵심 3개 중 2개 이상 파악
    if state.turn_count < 3:
        return False
    
    core_fields = ["idea_one_liner", "target_customer", "problem_statement"]
    filled_count = sum(1 for f in core_fields if state.hypotheses.get(f))
    
    return filled_count >= 2


# ============================================================================
# 메인 클래스
# ============================================================================

class InputRefiner:
    """대화형 입력 구체화 - 인터뷰어 스타일"""
    
    def __init__(self):
        self.llm = _get_llm("fast")
        self.llm_main = _get_llm("main")
        self.state = RefinerState()
        self.transcript: List[Dict[str, str]] = []
    
    def _generate_curiosity_angle(self) -> Optional[str]:
        """
        능동적 호기심 질문 생성
        - Exploration 단계에서 "다음에 무엇이 가장 궁금한지"를 LLM에게 물어봄
        - 이 의도를 system_prompt에 주입하여 자연스러운 대화 유도
        """
        # 너무 초반에는 호기심 질문 불필요
        if not self.state.hypotheses and self.state.turn_count < 2:
            return None
        
        current_state = _format_understanding(self.state)
        messages = [
            {
                "role": "system",
                "content": f"{CURIOSITY_PROMPT}\n\n[현재 이해 상태]\n{current_state}"
            },
            {
                "role": "user",
                "content": "현재 이해 상태를 보고 다음으로 궁금한 관점을 골라주세요."
            }
        ]
        
        try:
            response = self.llm.call(messages=messages)
            parsed = _extract_json_from_response(response)
            
            if parsed and parsed.get("suggested_angle"):
                return parsed["suggested_angle"]
        except Exception:
            pass  # 실패해도 대화 진행에 영향 없음
        
        return None
    
    def _should_extract_now(self, user_input: str) -> bool:
        """
        의미 기반 추출 트리거
        - 의미 있는 발화가 나왔을 때만 정보 추출
        - 불필요한 추출 감소 → 품질 ↑, 토큰 ↓
        """
        # 신호 단어: 핵심 정보를 담고 있을 가능성이 높은 표현들
        signal_words = [
            "결국", "그래서", "핵심은", "문제는", "가장", 
            "진짜", "중요한 건", "아마", "느낌상", "사실",
            "왜냐하면", "때문에", "그니까", "요약하면",
            "지금은", "현재", "대안", "대신", "경쟁"
        ]
        
        if any(word in user_input for word in signal_words):
            return True
        
        # Phase 전환 직전은 무조건 추출
        if self.state.phase == "structuring":
            return True
        
        # 긴 응답은 의미 있는 정보 포함 가능성 높음
        if len(user_input) > 100:
            return True
        
        return False
    
    def _call_conversation_llm(self, user_message: str) -> str:
        """대화용 LLM 호출 (자연어 응답)"""
        
        # Phase에 따라 프롬프트 선택
        if self.state.phase == "exploration":
            system_prompt = EXPLORATION_PROMPT.format(
                current_understanding=_format_understanding(self.state),
                conversation_summary=self._get_conversation_summary(),
            )
            
            # 🎯 능동적 호기심 질문 주입 (Exploration 단계에서만)
            curiosity_angle = self._generate_curiosity_angle()
            if curiosity_angle:
                system_prompt += f"\n\n[다음으로 궁금한 관점]\n{curiosity_angle}"
        else:
            system_prompt = STRUCTURING_PROMPT.format(
                current_understanding=_format_understanding(self.state),
                unclear_parts=_get_unclear_parts(self.state),
                conversation_summary=self._get_conversation_summary(),
            )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        
        response = self.llm.call(messages=messages)
        
        # 대화 기록 저장
        self.transcript.append({"role": "user", "content": user_message})
        self.transcript.append({"role": "assistant", "content": response})
        
        return response
    
    def _extract_info_from_conversation(self) -> None:
        """대화에서 정보 추출 (내부용, 사용자에게 노출 안 됨)"""
        
        # 전체 대화를 텍스트로
        conversation_text = "\n".join([
            f"{'사용자' if m['role'] == 'user' else '시스템'}: {m['content']}"
            for m in self.transcript
        ])
        
        messages = [
            {"role": "system", "content": f"{EXTRACTION_PROMPT}\n\n[대화 내용]\n{conversation_text}"},
            {"role": "user", "content": "위 대화에서 정보를 추출해주세요."},
        ]
        
        response = self.llm_main.call(messages=messages)
        parsed = _extract_json_from_response(response)
        
        if parsed:
            # 상태 업데이트
            for key in REQUIRED_FIELDS:
                value = parsed.get(key)
                if value and value != "null":
                    self.state.hypotheses[key] = value
            
            # confidence 업데이트
            conf = parsed.get("confidence", {})
            for key in REQUIRED_FIELDS:
                if key in conf:
                    self.state.confidence[key] = conf[key]
            
            # raw understanding
            if parsed.get("raw_understanding"):
                self.state.raw_understanding = parsed["raw_understanding"]
    
    def _get_conversation_summary(self) -> str:
        """최근 대화 요약 (최대 6개 메시지)"""
        recent = self.transcript[-6:]
        if not recent:
            return "(대화 시작)"
        
        return "\n".join([
            f"{'사용자' if m['role'] == 'user' else '시스템'}: {m['content'][:200]}..."
            if len(m['content']) > 200 else
            f"{'사용자' if m['role'] == 'user' else '시스템'}: {m['content']}"
            for m in recent
        ])
    
    def _finalize_inputs(self) -> Dict[str, Any]:
        """최종 inputs 생성 (기본값 적용)"""
        inputs = {}
        
        for key in REQUIRED_FIELDS:
            value = self.state.hypotheses.get(key)
            if value:
                inputs[key] = value
            elif key in DEFAULT_VALUES:
                inputs[key] = DEFAULT_VALUES[key]
                self.state.confidence[key] = "assumed"
            else:
                inputs[key] = f"(미정: {key})"
                self.state.confidence[key] = "missing"
        
        return inputs
    
    def _show_final_summary(self) -> str:
        """최종 요약 출력"""
        inputs = self._finalize_inputs()
        
        lines = [
            "\n" + "═" * 60,
            "📋 시장 검증 INPUT 최종 확인",
            "═" * 60,
        ]
        
        field_labels = {
            "idea_one_liner": "💡 아이디어",
            "target_customer": "👥 타깃 고객",
            "problem_statement": "🎯 해결할 문제",
            "current_alternatives": "🔄 현재 대안",
            "geo_market": "🌍 시장",
            "business_type": "💼 비즈니스 유형",
        }
        
        assumed_fields = []
        
        for key in REQUIRED_FIELDS:
            label = field_labels.get(key, key)
            value = inputs.get(key, "")
            conf = self.state.confidence.get(key, "medium")
            
            if conf == "assumed":
                lines.append(f"{label}: {value} (기본값)")
                assumed_fields.append(key)
            elif conf == "low":
                lines.append(f"{label}: {value} (추정)")
            else:
                lines.append(f"{label}: {value}")
        
        lines.append("─" * 60)
        
        if assumed_fields:
            lines.append(f"⚠️ 기본값 적용된 항목: {', '.join(assumed_fields)}")
        
        lines.append("\n이대로 시장 검증을 시작할까요?")
        lines.append("'done' 또는 '시작' → 진행 | 수정 내용 입력 → 반영")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def refine(self, initial_idea: Optional[str] = None) -> RefinerResult:
        """메인 대화 루프"""
        
        print("\n" + "═" * 60)
        print("🎯 Gap Foundry - 아이디어 인터뷰")
        print("═" * 60)
        print(f"🧠 모델: {self.llm.model}")
        print("─" * 60)
        print("아이디어를 자유롭게 이야기해주세요.")
        print("저는 먼저 이해하려고 노력할게요 😊")
        print("")
        print("명령어: 'done'(완료) | 'status'(현재 상태) | 'quit'(취소)")
        print("═" * 60 + "\n")
        
        # 초기 인사
        if initial_idea:
            print(f"📝 입력: {initial_idea}\n")
            response = self._call_conversation_llm(initial_idea)
            print(f"🤖 {response}\n")
            self.state.turn_count += 1
            
            # 정보 추출 (백그라운드)
            self._extract_info_from_conversation()
        else:
            print("🤖 안녕하세요! 어떤 아이디어를 생각하고 계신가요?")
            print("   편하게 이야기해주세요. 판단하지 않고 먼저 이해하려고 할게요.\n")
        
        # 메인 대화 루프 (max_turns 없음!)
        while True:
            try:
                user_input = input("📝 입력: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n취소되었습니다.")
                return RefinerResult(is_confirmed=False, turns_used=self.state.turn_count)
            
            if not user_input:
                continue
            
            cmd = user_input.lower().strip()
            
            # 명령어 처리
            if cmd in ["quit", "취소", "exit", "q"]:
                print("\n취소되었습니다.")
                return RefinerResult(is_confirmed=False, turns_used=self.state.turn_count)
            
            if cmd in ["status", "상태"]:
                print("\n" + _format_understanding(self.state) + "\n")
                continue
            
            if cmd in ["done", "완료", "시작", "start", "ok", "yes", "네", "ㅇ", "확인"]:
                # 최종 확인 단계
                if self.state.phase == "exploration":
                    # 아직 exploration이면 → structuring으로 전환
                    self.state.phase = "structuring"
                    self._extract_info_from_conversation()
                    print(self._show_final_summary())
                    continue
                else:
                    # 이미 structuring이면 → 완료
                    break
            
            # 대화 진행
            self.state.turn_count += 1
            
            # Structuring phase에서 수정 입력 시 → 반영 후 최종 화면 다시 표시
            if self.state.phase == "structuring":
                # 수정 내용을 대화에 추가하고 재추출
                self.transcript.append({"role": "user", "content": user_input})
                self._extract_info_from_conversation()
                print("\n✅ 수정 내용이 반영되었습니다!")
                print(self._show_final_summary())
                continue  # AI 대화 응답 건너뛰기
            
            # Phase 전환 체크 (exploration → structuring 제안)
            if self.state.phase == "exploration" and _should_transition_to_structuring(self.state):
                self._extract_info_from_conversation()
                
                # 자연스럽게 구조화 제안 (이 턴에서는 AI 응답 건너뛰기)
                if not self.state.exploration_done:
                    self.state.exploration_done = True
                    print("\n" + "─" * 50)
                    print("✅ 아이디어가 충분히 이해됐어요!")
                    print("─" * 50)
                    print("\n다음 중 하나를 선택해주세요:")
                    print("  👉 'done' 또는 '시작' → 정리된 내용 확인 후 시장 검증 시작")
                    print("  👉 계속 입력 → 더 이야기하고 싶으면 자유롭게\n")
                    continue  # AI 응답 건너뛰기
            
            # 대화 응답 (exploration phase에서만)
            response = self._call_conversation_llm(user_input)
            print(f"\n🤖 {response}\n")
            
            # 🎯 의미 기반 정보 추출 (핵심 발화가 있을 때만)
            if self._should_extract_now(user_input):
                self._extract_info_from_conversation()
        
        # 최종 inputs 생성
        final_inputs = self._finalize_inputs()
        
        # confidence flags 계산
        confidence_flags = {}
        for f in REQUIRED_FIELDS:
            conf = self.state.confidence.get(f, "medium")
            if conf == "assumed":
                confidence_flags[f] = "assumed"
            elif conf == "low":
                confidence_flags[f] = "low"
            elif not self.state.hypotheses.get(f):
                confidence_flags[f] = "missing"
            else:
                confidence_flags[f] = "ok"
        
        return RefinerResult(
            inputs=final_inputs,
            transcript=self.transcript,
            confidence_flags=confidence_flags,
            is_confirmed=True,
            turns_used=self.state.turn_count,
        )


# ============================================================================
# 공개 인터페이스
# ============================================================================

def refine_inputs(
    initial_idea: Optional[str] = None,
) -> Dict[str, Any]:
    """
    대화형으로 입력을 구체화하는 헬퍼 함수.
    
    Returns:
        dict with keys:
        - inputs
        - transcript
        - confidence_flags
        - is_confirmed
        - turns_used
        
        취소 시 빈 dict 반환
    """
    refiner = InputRefiner()
    result = refiner.refine(initial_idea)
    
    if not result.is_confirmed:
        return {}
    
    return {
        "inputs": result.inputs,
        "transcript": result.transcript,
        "confidence_flags": result.confidence_flags,
        "is_confirmed": result.is_confirmed,
        "turns_used": result.turns_used,
    }


# ============================================================================
# 직접 실행
# ============================================================================

if __name__ == "__main__":
    result = refine_inputs()
    
    if result:
        print("\n" + "═" * 60)
        print("✅ 최종 결과")
        print("═" * 60)
        print(f"턴 수: {result['turns_used']}")
        print(f"confidence: {result['confidence_flags']}")
        print(f"\ninputs:\n{json.dumps(result['inputs'], ensure_ascii=False, indent=2)}")
