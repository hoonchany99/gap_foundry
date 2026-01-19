from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

import yaml
from crewai import Agent, Task, Crew, Process, LLM


# ============================================================================
# 진행 상황 표시 (Progress Tracker)
# ============================================================================

class ProgressTracker:
    """태스크 진행 상황을 추적하고 표시하는 클래스"""
    
    TASK_LABELS = {
        "discover_competitors": ("🔍", "경쟁사 발굴", "2~3분", "직접/간접 경쟁사 15개+ 검색"),
        "compact_competitors": ("📦", "경쟁사 압축", "30초", "상위 8개 핵심 정보 추출"),
        "analyze_channels": ("📊", "채널/메시지 분석", "3~4분", "마케팅 채널 & 메시지 패턴 분석"),
        "extract_value_props": ("💎", "가치제안 추출", "3~4분", "USP, 가격, 마찰점 추출"),
        "summarize_channels_vp": ("📋", "채널/VP 압축", "30초", "핵심 패턴 요약"),
        "mine_gaps": ("🕳️", "빈틈 가설 도출", "2~3분", "시장 기회 가설 생성"),
        "summarize_research": ("📋", "리서치 요약", "1~2분", "전체 리서치 압축"),
        "create_pov_and_positioning": ("🎯", "POV/포지셔닝 설계", "3~4분", "차별화 전략 수립"),
        "red_team_review": ("👹", "레드팀 검토", "2~3분", "날카로운 반증 & 판정"),
        "revise_positioning": ("✏️", "포지셔닝 수정", "2~3분", "피드백 반영 수정"),
        "red_team_recheck": ("👹", "레드팀 재검토", "1~2분", "수정본 재검토"),
        "final_step1_report": ("📝", "최종 리포트 작성", "2~3분", "Go/No-Go 결론 도출"),
    }
    
    # 단계별 진행률 범위 설정
    STAGE_PROGRESS = {
        "pass1": (5, 70),       # Pass 1: 5% → 70%
        "revision": (70, 85),   # Revision: 70% → 85%
        "final_report": (85, 100),  # Final Report: 85% → 100%
    }
    
    def __init__(self, task_order: List[str], include_revision: bool = False, is_revision: bool = False, external_callback: Callable = None, stage: str = "pass1"):
        self.task_order = task_order
        self.total_tasks = len(task_order)
        self.current_task_idx = 0
        self.task_start_times: Dict[str, float] = {}
        self.task_end_times: Dict[str, float] = {}
        self.start_time = time.time()
        self.include_revision = include_revision
        self.is_revision = is_revision
        self.external_callback = external_callback  # API 연동용 외부 콜백
        self.stage = stage  # 현재 단계 (pass1, revision, final_report)
        
    def _get_label(self, task_id: str) -> Tuple[str, str, str, str]:
        """태스크 ID에 대한 (이모지, 한글명, 예상시간, 설명) 반환"""
        return self.TASK_LABELS.get(task_id, ("⚙️", task_id, "?분", "처리 중"))
    
    def _make_progress_bar(self, current: int, total: int, width: int = 30) -> str:
        """프로그레스 바 생성"""
        filled = int(width * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (width - filled)
        percent = int(100 * current / total) if total > 0 else 0
        return f"[{bar}] {percent}%"
    
    def print_header(self):
        """실행 시작 헤더 출력"""
        if self.is_revision:
            mode = "🔄 Revision-only 모드"
            est_time = "3~5분"
        elif self.include_revision:
            mode = "Auto-Revise 모드"
            est_time = "15~25분"
        else:
            mode = "기본 모드"
            est_time = "15~25분"
        
        print("\n" + "╔" + "═" * 63 + "╗")
        print(f"║ 🚀 STEP1 시장검증 실행 중... ({mode})" + " " * (44 - len(mode)) + "║")
        print("╠" + "═" * 63 + "╣")
        print(f"║ 📋 총 {self.total_tasks}개 태스크 | 예상 소요: {est_time}" + " " * (35 - len(est_time)) + "║")
        print("╚" + "═" * 63 + "╝")
        
        # 태스크 목록 미리보기
        print("\n📋 실행 예정 태스크:")
        for i, task_id in enumerate(self.task_order):
            emoji, label, est, desc = self._get_label(task_id)
            status = "⏳" if i == 0 else "○"
            print(f"   {status} {i+1}. {emoji} {label} ({est}) - {desc}")
        print()
    
    def on_task_start(self, task_id: str):
        """태스크 시작 시 호출"""
        self.task_start_times[task_id] = time.time()
        emoji, label, est_time, desc = self._get_label(task_id)
        
        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"
        
        # 프로그레스 바
        progress_bar = self._make_progress_bar(self.current_task_idx, self.total_tasks)
        
        print(f"\n{'─' * 65}")
        print(f"▶ [{self.current_task_idx + 1}/{self.total_tasks}] {emoji} {label} 시작")
        print(f"  {progress_bar}")
        print(f"  💡 {desc}")
        print(f"  ⏱️ 예상: {est_time} | 경과: {elapsed_str}")
        print(f"{'─' * 65}")
        
        # 외부 콜백 호출 (API 연동)
        # 단계별 진행률 범위 사용
        if self.external_callback:
            base_progress, max_progress = self.STAGE_PROGRESS.get(self.stage, (5, 95))
            task_progress_range = max_progress - base_progress
            progress_percent = base_progress + int((self.current_task_idx / self.total_tasks) * task_progress_range)
            self.external_callback(
                task_id=task_id,
                status="started",
                progress=progress_percent,
                step=f"{emoji} {label} 시작...",
            )
    
    def on_task_end(self, task_id: str, output_preview: str = ""):
        """태스크 완료 시 호출"""
        self.task_end_times[task_id] = time.time()
        duration = self.task_end_times[task_id] - self.task_start_times.get(task_id, self.start_time)
        duration_str = f"{int(duration // 60)}분 {int(duration % 60)}초"
        
        emoji, label, _, _ = self._get_label(task_id)
        
        self.current_task_idx += 1
        
        # 결과 요약 생성
        result_summary = self._extract_result_summary(task_id, output_preview)
        
        print(f"\n✅ {emoji} {label} 완료 ({duration_str})")
        
        # 외부 콜백 호출 (API 연동)
        # 단계별 진행률 범위 사용
        if self.external_callback:
            base_progress, max_progress = self.STAGE_PROGRESS.get(self.stage, (5, 95))
            task_progress_range = max_progress - base_progress
            progress_percent = base_progress + int((self.current_task_idx / self.total_tasks) * task_progress_range)
            self.external_callback(
                task_id=task_id,
                status="completed",
                progress=progress_percent,
                step=f"{emoji} {label} ✅ 완료",
            )
        if result_summary:
            print(f"   └─ 📌 {result_summary}")
        
        # 남은 태스크 예상
        if self.current_task_idx < self.total_tasks:
            remaining = self.total_tasks - self.current_task_idx
            avg_time = (time.time() - self.start_time) / self.current_task_idx
            est_remaining = avg_time * remaining
            est_min = int(est_remaining // 60)
            
            # 다음 태스크 미리보기
            next_task = self.task_order[self.current_task_idx]
            next_emoji, next_label, next_est, _ = self._get_label(next_task)
            
            print(f"   └─ ⏳ 남은 시간: ~{est_min}분 | 다음: {next_emoji} {next_label}")
    
    def _extract_result_summary(self, task_id: str, output: str) -> str:
        """태스크 결과에서 핵심 요약 추출"""
        if not output:
            return ""
        
        output_lower = output.lower()
        
        # 태스크별 요약 추출
        if task_id == "discover_competitors":
            # 경쟁사 수 추출
            import re
            items_match = re.search(r'"items"\s*:\s*\[(.*?)\]', output, re.DOTALL)
            if items_match:
                items_count = items_match.group(1).count('"name"')
                return f"경쟁사 {items_count}개 발굴"
        
        if task_id == "mine_gaps":
            # gap 수 추출
            gap_count = output.count('"gap_id"') or output.count('gap_')
            if gap_count > 0:
                return f"빈틈 가설 {gap_count}개 도출"
        
        if task_id in ["red_team_review", "red_team_recheck"]:
            # VERDICT 추출
            if "VERDICT: PASS" in output.upper():
                return "✅ VERDICT: PASS"
            elif "VERDICT: FAIL" in output.upper():
                return "❌ VERDICT: FAIL"
        
        if task_id == "create_pov_and_positioning":
            # Option 수 추출
            option_count = output.lower().count("option ")
            if option_count > 0:
                return f"포지셔닝 Option {min(option_count, 3)}개 생성"
        
        # 기본: 첫 80자
        preview = output[:80].replace("\n", " ").strip()
        if len(output) > 80:
            preview += "..."
        return preview if preview else ""
    
    def print_summary(self):
        """실행 완료 요약 출력"""
        total_time = time.time() - self.start_time
        total_min = int(total_time // 60)
        total_sec = int(total_time % 60)
        
        print("\n" + "╔" + "═" * 63 + "╗")
        print(f"║ ✅ STEP1 실행 완료!                                           ║")
        print("╠" + "═" * 63 + "╣")
        print(f"║ ⏱️ 총 소요 시간: {total_min}분 {total_sec}초" + " " * (40 - len(f"{total_min}분 {total_sec}초")) + "║")
        print("╚" + "═" * 63 + "╝")
        
        # 태스크별 소요 시간 (바 그래프)
        print("\n📊 태스크별 소요 시간:")
        max_duration = max(
            (self.task_end_times.get(t, 0) - self.task_start_times.get(t, 0))
            for t in self.task_order
        ) if self.task_order else 1
        
        for task_id in self.task_order:
            if task_id in self.task_end_times and task_id in self.task_start_times:
                duration = self.task_end_times[task_id] - self.task_start_times[task_id]
                emoji, label, _, _ = self._get_label(task_id)
                
                # 미니 바 그래프
                bar_width = int(20 * duration / max_duration) if max_duration > 0 else 0
                bar = "▓" * bar_width + "░" * (20 - bar_width)
                
                duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}"
                print(f"   {emoji} {label[:12]:<12} {bar} {duration_str}")
        
        print()


# 전역 progress tracker (콜백에서 접근용)
_progress_tracker: Optional[ProgressTracker] = None


def _make_step_callback(tracker: ProgressTracker) -> Callable:
    """
    CrewAI step_callback 함수 생성
    - 에이전트가 thinking/action을 수행할 때마다 호출됨
    - 실시간으로 무엇을 하고 있는지 표시
    """
    last_agent = [None]
    last_action = [None]
    step_count = [0]
    tool_call_count = [0]
    
    # 에이전트 역할 → 한글명 매핑
    AGENT_LABELS = {
        "competitor_discovery_agent": "🔍 경쟁사 발굴",
        "channel_intel_agent": "📊 채널 분석",
        "vp_extractor_agent": "💎 VP 추출",
        "gap_miner_agent": "🕳️ 빈틈 발굴",
        "research_summarizer_agent": "📋 리서치 요약",
        "pov_strategist_agent": "🎯 POV 전략",
        "red_team_agent": "👹 레드팀",
    }
    
    def _format_elapsed() -> str:
        elapsed = time.time() - tracker.start_time
        return f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"
    
    def _get_agent_label(agent_name: str) -> str:
        """에이전트 이름을 한글 라벨로 변환"""
        if not agent_name:
            return "🤖 에이전트"
        agent_lower = agent_name.lower().replace(" ", "_")
        for key, label in AGENT_LABELS.items():
            if key in agent_lower or agent_lower in key:
                return label
        # 원본에서 추출 시도
        if "competitor" in agent_lower:
            return "🔍 경쟁사 발굴"
        if "channel" in agent_lower:
            return "📊 채널 분석"
        if "vp" in agent_lower or "value" in agent_lower:
            return "💎 VP 추출"
        if "gap" in agent_lower:
            return "🕳️ 빈틈 발굴"
        if "summar" in agent_lower:
            return "📋 리서치 요약"
        if "pov" in agent_lower or "position" in agent_lower:
            return "🎯 POV 전략"
        if "red" in agent_lower:
            return "👹 레드팀"
        return f"🤖 {agent_name[:20]}"
    
    def _parse_tool_info(step_output) -> Optional[Tuple[str, str]]:
        """도구 호출 정보 추출 → (tool_name, tool_input)"""
        tool_name = None
        tool_input = None
        
        # 다양한 속성 시도
        if hasattr(step_output, 'tool'):
            tool_name = str(step_output.tool)
        if hasattr(step_output, 'tool_input'):
            ti = step_output.tool_input
            if isinstance(ti, dict):
                # search_query, query, url 등 추출
                tool_input = ti.get('search_query') or ti.get('query') or ti.get('url') or ti.get('website_url') or str(ti)[:60]
            else:
                tool_input = str(ti)[:60]
        
        # action에서 도구 정보 추출 시도
        if not tool_name and hasattr(step_output, 'action'):
            action = str(step_output.action)
            if 'search' in action.lower():
                tool_name = 'search'
            elif 'scrape' in action.lower() or 'website' in action.lower():
                tool_name = 'scrape'
        
        if tool_name:
            return (tool_name, tool_input or "")
        return None
    
    def callback(step_output):
        nonlocal tool_call_count
        try:
            step_count[0] += 1
            
            # 에이전트 이름 추출
            agent_name = None
            if hasattr(step_output, 'agent'):
                agent_obj = step_output.agent
                if hasattr(agent_obj, 'role'):
                    agent_name = agent_obj.role
                elif isinstance(agent_obj, str):
                    agent_name = agent_obj
            
            # 에이전트가 바뀌면 표시
            if agent_name and agent_name != last_agent[0]:
                label = _get_agent_label(agent_name)
                print(f"\n   {label} 작업 중... [{_format_elapsed()}]")
                last_agent[0] = agent_name
                tool_call_count[0] = 0  # 새 에이전트면 도구 카운트 리셋
            
            # 도구 호출 감지 및 표시
            tool_info = _parse_tool_info(step_output)
            if tool_info:
                tool_name, tool_input = tool_info
                action_key = f"{tool_name}:{tool_input}"
                
                # 같은 도구 호출 중복 방지
                if action_key != last_action[0]:
                    tool_call_count[0] += 1
                    last_action[0] = action_key
                    
                    # 도구 종류에 따른 이모지/메시지
                    if 'search' in tool_name.lower():
                        query_preview = tool_input[:50] if tool_input else "..."
                        print(f"      🔎 검색 중: \"{query_preview}\"")
                    elif 'scrape' in tool_name.lower() or 'website' in tool_name.lower():
                        url_preview = tool_input[:40] if tool_input else "..."
                        print(f"      🌐 웹 분석 중: {url_preview}")
                    elif 'read' in tool_name.lower() or 'file' in tool_name.lower():
                        print(f"      📄 파일 읽는 중...")
                    else:
                        print(f"      🔧 {tool_name[:30]} 실행 중...")
            
            # 생각/추론 과정 표시 (가끔)
            thought = None
            if hasattr(step_output, 'thought'):
                thought = str(step_output.thought)
            elif hasattr(step_output, 'log'):
                thought = str(step_output.log)
            
            # 중요 키워드가 포함된 생각만 표시
            if thought and step_count[0] % 5 == 0:  # 5스텝마다 한 번
                thought_preview = thought[:60].replace("\n", " ")
                if any(kw in thought.lower() for kw in ['found', 'analyzing', 'comparing', '발견', '분석', '비교', '검토']):
                    print(f"      💭 {thought_preview}...")
            
        except Exception:
            pass  # 에러 무시하고 계속 진행
    
    return callback


def _make_task_callback(tracker: ProgressTracker) -> Callable:
    """
    CrewAI task_callback 함수 생성
    - 태스크가 완료될 때마다 호출됨
    """
    def callback(task_output):
        try:
            # task_output에서 정보 추출
            raw = getattr(task_output, "raw", "") or ""
            
            # 현재 태스크 완료 처리
            if tracker.current_task_idx < len(tracker.task_order):
                task_id = tracker.task_order[tracker.current_task_idx]
                
                # 시작 시간이 없으면 지금 시작한 것으로 처리
                if task_id not in tracker.task_start_times:
                    tracker.task_start_times[task_id] = time.time()
                
                # 완료 처리
                tracker.on_task_end(task_id, raw[:200])
                
                # 다음 태스크 시작 알림
                if tracker.current_task_idx < len(tracker.task_order):
                    next_task_id = tracker.task_order[tracker.current_task_idx]
                    tracker.on_task_start(next_task_id)
        except Exception:
            pass  # 에러 무시하고 계속 진행
    
    return callback

# ---- Tools (웹 검색/스크래핑) ----
# SERPER_API_KEY 환경변수가 설정되어 있어야 동작
#
# 운영급 5중 가드레일 #1: Tool 출력 하드리밋
# - 검색: 1800자 (스니펫 위주)
# - 스크래핑: 800자 (Hero copy 영역만)
#
try:
    from crewai_tools import SerperDevTool, ScrapeWebsiteTool
    from crewai.tools import BaseTool
    from pydantic import Field

    TOOLS_AVAILABLE = True
    
    # ---- 검색 결과 Hard Limit 래퍼 ----
    class LimitedSerperTool(BaseTool):
        """
        SerperDevTool 래퍼: 검색 결과를 hard limit으로 자른다.
        
        검색 결과도 생각보다 길어질 수 있음.
        스니펫만 사용하도록 강제해서 context 폭발 방지.
        """
        
        name: str = "Search the internet"
        description: str = "A tool that searches the internet for information. Input should be a search query."
        max_chars: int = Field(default=1800, description="Maximum characters to return")
        
        def _run(self, query: str) -> str:
            """검색 후 결과를 max_chars로 자른다."""
            inner_tool = SerperDevTool()
            
            try:
                result = inner_tool.run(search_query=query)
                if isinstance(result, str) and len(result) > self.max_chars:
                    truncated = result[:self.max_chars]
                    # 마지막 완전한 문장까지만
                    last_period = max(
                        truncated.rfind('. '),
                        truncated.rfind('.\n'),
                        truncated.rfind('\n\n'),
                    )
                    if last_period > self.max_chars // 2:
                        truncated = truncated[:last_period + 1]
                    return truncated + f"\n[...검색 결과 {len(result) - len(truncated)}자 생략...]"
                return result
            except Exception as e:
                return f"[검색 실패: {e}] 쿼리: {query}"
    
    # ---- 스크래핑 결과 Hard Limit 래퍼 ----
    class LimitedScrapeWebsiteTool(BaseTool):
        """
        ScrapeWebsiteTool 래퍼: 스크래핑 결과를 hard limit으로 자른다.
        
        TPM 관리의 핵심:
        - 스크래핑 결과가 너무 크면 context가 폭발
        - 프롬프트 지시만으로는 제어 불가
        - 코드에서 강제로 자르는 것이 유일한 해결책
        """
        
        name: str = "Read website content"
        description: str = "A tool that scrapes and reads website content. Input should be a valid URL."
        max_chars: int = Field(default=800, description="Maximum characters to return")
        
        def _run(self, website_url: str) -> str:
            """웹사이트 스크래핑 후 결과를 max_chars로 자른다."""
            inner_tool = ScrapeWebsiteTool()
            
            try:
                result = inner_tool.run(website_url=website_url)
                if isinstance(result, str) and len(result) > self.max_chars:
                    # 문장 단위로 자르기 시도
                    truncated = result[:self.max_chars]
                    # 마지막 완전한 문장까지만
                    last_period = max(
                        truncated.rfind('. '),
                        truncated.rfind('.\n'),
                        truncated.rfind('! '),
                        truncated.rfind('? '),
                    )
                    if last_period > self.max_chars // 2:
                        truncated = truncated[:last_period + 1]
                    return truncated + f"\n\n[... {len(result) - len(truncated)}자 생략됨 ...]"
                return result
            except Exception as e:
                return f"[스크래핑 실패: {e}] URL: {website_url}"

except ImportError:
    TOOLS_AVAILABLE = False
    SerperDevTool = None  # type: ignore[assignment]
    ScrapeWebsiteTool = None  # type: ignore[assignment]
    LimitedSerperTool = None  # type: ignore[assignment]
    LimitedScrapeWebsiteTool = None  # type: ignore[assignment]


# ---- LLM 설정 ----
# 환경변수로 모델명 오버라이드 가능
#
# 모델 라인업 (OpenAI GPT-4.1 시리즈):
#   - gpt-4.1       : 최고 품질, 복잡한 추론/창의성
#   - gpt-4.1-mini  : 균형 (품질 vs 속도/비용)
#   - gpt-4.1-nano  : 초경량, 단순 추출/정리 전용
#
# LLM 배치 전략:
#   🧠 Main (gpt-4.1): orchestrator, gap_miner, red_team
#      → 최종 판단/통합, 창의+논리, 날카로운 반증이 필요
#   ⚡ Fast (gpt-4.1-mini): competitor_discovery, channel_intel, vp_extractor, pov_strategist
#      → 검색 정리, 패턴 추출, 구조화 위주 (결과가 약하면 pov_strategist만 Main으로 올리기)
#   🚀 Nano (gpt-4.1-nano): 현재 미사용 (필요 시 추출 전용 태스크에 적용 가능)
#
DEFAULT_MAIN_MODEL = "gpt-4.1"
DEFAULT_FAST_MODEL = "gpt-4.1-mini"
DEFAULT_NANO_MODEL = "gpt-4.1-nano"


# LLM 응답 길이 설정 (max_tokens)
# Sequential 프로세스에서는 누적 메모리 문제 없음 → 넉넉하게 설정 가능
# - main (gpt-4.1): 3000 토큰 (복잡한 분석/판단/POV/red_team)
# - fast (gpt-4.1-mini): 2500 토큰 (구조화/추출)
# - nano: 1500 토큰 (단순 추출)
MAX_TOKENS_BY_TYPE = {
    "main": 3000,
    "fast": 2500,
    "nano": 1500,
}


def _get_llm(model_type: str = "main", max_tokens: Optional[int] = None) -> LLM:
    """
    LLM 인스턴스를 생성한다.
    
    Args:
        model_type: "main" | "fast" | "nano"
        max_tokens: 응답 최대 토큰 수 (None이면 기본값 사용)
    
    환경변수:
        MAIN_LLM_MODEL: 핵심 에이전트용 모델 (기본: gpt-4.1)
        FAST_LLM_MODEL: 보조 에이전트용 모델 (기본: gpt-4.1-mini)
        NANO_LLM_MODEL: 초경량 에이전트용 모델 (기본: gpt-4.1-nano)
    """
    if model_type == "main":
        model = os.getenv("MAIN_LLM_MODEL", DEFAULT_MAIN_MODEL)
    elif model_type == "nano":
        model = os.getenv("NANO_LLM_MODEL", DEFAULT_NANO_MODEL)
    else:  # fast
        model = os.getenv("FAST_LLM_MODEL", DEFAULT_FAST_MODEL)
    
    # max_tokens 설정 (운영급 가드레일 #4)
    tokens = max_tokens or MAX_TOKENS_BY_TYPE.get(model_type, 1500)
    
    return LLM(model=model, max_tokens=tokens)


class Step1CrewFactory:
    """
    STEP 1 (경쟁 분석 + 아이디어 고도화) CrewAI Crew 생성기

    - config/agents.yaml, config/tasks.yaml을 로드
    - tasks.yaml의 task id를 그대로 Task 키로 사용
    - tasks.yaml의 context 의존성을 위상 정렬로 해결 (생성 시점에 context 전달)
    - hierarchical process에서 manager(orchestrator)를 workers와 분리
    """

    def __init__(self) -> None:
        # 이 파일(src/gap_foundry/crew.py)을 기준으로 config 경로를 고정
        base_dir = Path(__file__).resolve().parent
        self.config_dir = base_dir / "config"
        self.agents_path = self.config_dir / "agents.yaml"
        self.tasks_path = self.config_dir / "tasks.yaml"

        if not self.agents_path.exists():
            raise FileNotFoundError(f"agents.yaml not found: {self.agents_path}")
        if not self.tasks_path.exists():
            raise FileNotFoundError(f"tasks.yaml not found: {self.tasks_path}")

        self.agents_cfg = self._load_yaml(self.agents_path)
        self.tasks_cfg = self._load_yaml(self.tasks_path)

        # ---- 웹 리서치 도구 초기화 ----
        self.search_tool: Optional[Any] = None
        self.scrape_tool: Optional[Any] = None

        if TOOLS_AVAILABLE and os.getenv("SERPER_API_KEY"):
            # 운영급 가드레일 #1: Tool 하드리밋
            # - 검색: 1800자 (스니펫 위주)
            # - 스크래핑: 800자 (Hero copy 영역만)
            if LimitedSerperTool:
                self.search_tool = LimitedSerperTool(max_chars=1800)
            else:
                self.search_tool = SerperDevTool()
            
            if LimitedScrapeWebsiteTool:
                self.scrape_tool = LimitedScrapeWebsiteTool(max_chars=800)
            else:
                self.scrape_tool = ScrapeWebsiteTool() if ScrapeWebsiteTool else None
            print("✅ 검색/스크래핑 도구 활성화됨 (SERPER_API_KEY 감지, 하드리밋 적용)")
        else:
            print("⚠️  검색 도구 비활성화: SERPER_API_KEY 환경변수 설정 또는 crewai-tools 설치 필요")
            print("   → 실행은 되지만, 경쟁사/채널/가치제안 분석이 '추론'에 의존할 수 있습니다.")

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"YAML root must be a mapping/dict: {path}")
        return data

    # -------------------------
    # Agents
    # -------------------------
    def create_agents(self) -> Tuple[Agent, Dict[str, Agent]]:
        """
        agents.yaml의 키 이름과 동일한 키로 Agent를 만든다.
        tasks.yaml의 `agent:` 필드가 이 키를 참조하므로 정확히 일치해야 함.

        Returns:
            (manager_agent, worker_agents_dict)
            - manager: hierarchical process 조율자(orchestrator)
            - workers: 실제 태스크 실행자들만 포함
        
        LLM 배치 전략:
            - 🧠 main (gpt-4.1): orchestrator, gap_miner, red_team
              → 최종 판단/통합, 창의+논리(빈틈 가설), 날카로운 반증
            - ⚡ fast (gpt-4.1-mini): competitor_discovery, channel_intel, vp_extractor, pov_strategist
              → 검색 정리, 패턴 추출, 구조화 위주
              → pov_strategist는 결과가 약하면 main으로 올리기
        """
        # LLM 인스턴스 (재사용)
        main_llm = _get_llm("main")
        fast_llm = _get_llm("fast")

        print(f"🧠 Main LLM: {main_llm.model}")
        print(f"⚡ Fast LLM: {fast_llm.model}")

        # 도구 세트 구성
        search_only: List[Any] = []
        if self.search_tool:
            search_only.append(self.search_tool)

        search_and_scrape: List[Any] = []
        if self.search_tool:
            search_and_scrape.append(self.search_tool)
        if self.scrape_tool:
            search_and_scrape.append(self.scrape_tool)

        def make(
            name: str,
            llm: LLM,
            tools: Optional[List[Any]] = None,
        ) -> Agent:
            if name not in self.agents_cfg:
                raise KeyError(f"Agent '{name}' not found in agents.yaml")
            return Agent(
                **self.agents_cfg[name],
                llm=llm,
                tools=tools or [],
            )

        # ---- Manager (조율자) - Main LLM ----
        # Note: Sequential 프로세스에서는 manager 누적 메모리 문제 없음
        #       → gpt-4.1 사용해도 TPM 안전 + 판단 품질 유지
        manager = make("orchestrator", llm=main_llm)

        # ---- Workers (실행자) ----
        workers: Dict[str, Agent] = {}

        # ⚡ Fast LLM: 검색/정보 수집/구조화 중심
        workers["competitor_discovery"] = make(
            "competitor_discovery", llm=fast_llm, tools=search_only
        )
        workers["channel_intel"] = make(
            "channel_intel", llm=fast_llm, tools=search_and_scrape
        )
        workers["vp_extractor"] = make(
            "vp_extractor", llm=fast_llm, tools=search_and_scrape
        )
        # research_summarizer: context 압축 담당 (fast로 충분)
        workers["research_summarizer"] = make("research_summarizer", llm=fast_llm)
        # pov_strategist: 요약본 기반으로 작업하므로 fast 유지
        workers["pov_strategist"] = make("pov_strategist", llm=fast_llm)

        # 🧠 Main LLM: 창의성/논리/반증 중심 (품질 차이가 크게 남)
        workers["gap_miner"] = make("gap_miner", llm=main_llm)
        workers["red_team"] = make("red_team", llm=main_llm)

        return manager, workers

    # -------------------------
    # Tasks
    # -------------------------
    def create_tasks(
        self, 
        workers: Dict[str, Agent], 
        manager: Agent,
        allowed_task_ids: Optional[List[str]] = None,
    ) -> Dict[str, Task]:
        """
        tasks.yaml의 키 이름을 그대로 Task id로 사용한다.
        tasks.yaml의 `context:`는 '이전 task id' 목록이므로,
        위상 정렬(topological sort) 순서로 Task를 생성하여
        생성 시점에 context(list)를 전달한다.

        Args:
            allowed_task_ids: 생성할 태스크 ID 목록. None이면 모든 태스크 생성.
                             이 목록에 없는 태스크는 context에서도 무시됨.

        - 사후 할당(task.context = [...])은 버전 호환 문제가 있을 수 있어 피한다.
        - context는 None 대신 항상 list를 넘긴다(빈 리스트 허용).
        """
        all_agents: Dict[str, Agent] = {**workers, "orchestrator": manager}
        tasks: Dict[str, Task] = {}

        # allowed_task_ids가 지정되면 그것만, 아니면 전체
        if allowed_task_ids is not None:
            remaining = set(tid for tid in allowed_task_ids if tid in self.tasks_cfg)
            allowed_set = set(allowed_task_ids)
        else:
            remaining = set(self.tasks_cfg.keys())
            allowed_set = None  # 전체 허용

        while remaining:
            progress = False

            for task_id in list(remaining):
                task_cfg = self.tasks_cfg.get(task_id, {})
                if not isinstance(task_cfg, dict):
                    raise ValueError(f"Task '{task_id}' config must be a mapping/dict")

                ctx_ids_raw: List[str] = task_cfg.get("context") or []
                
                # allowed_set이 있으면, context에서 허용된 것만 필터링
                # (revision 태스크가 없을 때 final_report가 recheck를 무시하도록)
                if allowed_set is not None:
                    ctx_ids = [c for c in ctx_ids_raw if c in allowed_set]
                else:
                    ctx_ids = ctx_ids_raw

                # 모든 의존 task가 이미 생성되었는지 확인
                if all(c in tasks for c in ctx_ids):
                    agent_key = task_cfg.get("agent")
                    if agent_key not in all_agents:
                        raise KeyError(
                            f"Task '{task_id}' references unknown agent '{agent_key}'. "
                            f"Known agents: {list(all_agents.keys())}"
                )

                    context_tasks = [tasks[c] for c in ctx_ids]

                    tasks[task_id] = Task(
                        description=task_cfg.get("description", "") or "",
                        expected_output=task_cfg.get("expected_output", "") or "",
                        agent=all_agents[agent_key],
                        context=context_tasks,
                    )

                    remaining.remove(task_id)
                    progress = True

            if not progress:
                blocked = {
                    tid: (self.tasks_cfg[tid].get("context") or [])
                    for tid in remaining
                }
                raise ValueError(
                    "Circular dependency or missing context detected in tasks.yaml.\n"
                    f"Blocked tasks and their contexts: {blocked}\n"
                    "→ tasks.yaml의 context가 존재하는 task id를 참조하는지, 순환참조가 없는지 확인하세요."
                )

        return tasks

    # -------------------------
    # Crew
    # -------------------------
    def build(
        self, 
        include_revision: bool = False,
        show_progress: bool = True,
        external_callback: Callable = None,
    ) -> Tuple[Crew, Optional[ProgressTracker]]:
        """
        STEP1 Crew를 빌드한다.
        
        Args:
            include_revision: True면 revision 태스크 포함 (revise_positioning, red_team_recheck)
            show_progress: True면 진행 상황 표시용 ProgressTracker 반환
            external_callback: API 연동용 외부 콜백 함수 (task_id, status, progress, step 인자)
        
        Returns:
            (Crew, ProgressTracker) 또는 (Crew, None)
        """
        manager, workers = self.create_agents()

        if include_revision:
            # Revision 포함 전체 플로우
            task_order = [
                "discover_competitors",
                "compact_competitors",  # 경쟁사 정보 압축 (TPM 최적화)
                "analyze_channels",
                "extract_value_props",
                "summarize_channels_vp",  # 채널/VP 압축 (가드레일 #3)
                "mine_gaps",
                "summarize_research",  # 요약 태스크 (context 슬림화)
                "create_pov_and_positioning",
                "red_team_review",
                "revise_positioning",
                "red_team_recheck",
                "final_step1_report",
            ]
        else:
            # 기본 플로우 (revision 없음)
            task_order = [
                "discover_competitors",
                "compact_competitors",  # 경쟁사 정보 압축 (TPM 최적화)
                "analyze_channels",
                "extract_value_props",
                "summarize_channels_vp",  # 채널/VP 압축 (가드레일 #3)
                "mine_gaps",
                "summarize_research",  # 요약 태스크 (context 슬림화)
                "create_pov_and_positioning",
                "red_team_review",
                "final_step1_report",
            ]

        # task_order에 있는 것만 생성 (revision 없을 때 recheck context 무시)
        tasks = self.create_tasks(workers, manager, allowed_task_ids=task_order)

        missing = [t for t in task_order if t not in tasks]
        if missing:
            raise KeyError(
                f"task_order contains unknown task ids: {missing}. "
                f"Available tasks: {list(tasks.keys())}"
            )

        # 진행 상황 추적기 (외부 콜백 포함) - Pass 1: 5~70%
        tracker = ProgressTracker(task_order, include_revision, external_callback=external_callback, stage="pass1") if show_progress else None

        # 콜백 설정
        step_callback = _make_step_callback(tracker) if tracker else None
        task_callback = _make_task_callback(tracker) if tracker else None

        # Sequential 프로세스: 각 task는 자신의 context만 참조
        # Hierarchical의 manager 누적 메모리 문제 해결
        # → TPM 폭발 방지 + gpt-4.1 유지 가능
        crew = Crew(
            agents=list(workers.values()),
            tasks=[tasks[t] for t in task_order],
            process=Process.sequential,  # hierarchical → sequential
            verbose=True,  # 에이전트 결과물 생성에 필요
            step_callback=step_callback,
            task_callback=task_callback,
        )
        
        return crew, tracker

    def build_revision_only(
        self,
        show_progress: bool = False,
        external_callback: Callable = None,
    ) -> Tuple[Crew, Optional["ProgressTracker"]]:
        """
        Revision 태스크만 실행하는 Crew를 빌드한다 (final_report 제외).
        (2-stage 실행의 Stage A-Pass2: 1차에서 LANDING_HOLD일 때)
        
        final_step1_report는 Stage B에서 verdict를 inputs로 받아 별도 실행.
        
        주의: 이전 실행의 결과가 inputs에 포함되어 있어야 함:
              - previous_positioning_output: create_pov_and_positioning 결과
              - previous_red_team_output: red_team_review 결과
        
        Returns:
            (Crew, ProgressTracker 또는 None)
        """
        manager, workers = self.create_agents()

        task_order = [
            "revise_positioning",
            "red_team_recheck",
            # final_step1_report는 Stage B에서 별도 실행
        ]

        # revision-only 태스크만 생성 (context 필터링 적용)
        tasks = self.create_tasks(workers, manager, allowed_task_ids=task_order)

        missing = [t for t in task_order if t not in tasks]
        if missing:
            raise KeyError(
                f"task_order contains unknown task ids: {missing}. "
                f"Available tasks: {list(tasks.keys())}"
            )

        # Progress tracker 설정 - Revision: 70~85%
        tracker = ProgressTracker(task_order, is_revision=True, external_callback=external_callback, stage="revision") if show_progress else None
        step_callback = _make_step_callback(tracker) if tracker else None
        task_callback = _make_task_callback(tracker) if tracker else None

        # Sequential 프로세스 (revision-only도 동일)
        crew = Crew(
            agents=list(workers.values()),
            tasks=[tasks[t] for t in task_order],
            process=Process.sequential,  # hierarchical → sequential
            verbose=True,  # 에이전트 결과물 생성에 필요
            step_callback=step_callback,
            task_callback=task_callback,
        )
        
        return crew, tracker

    def build_without_final_report(
        self,
        include_revision: bool = False,
        show_progress: bool = False,
        external_callback: Callable = None,
    ) -> Tuple[Crew, Optional["ProgressTracker"]]:
        """
        final_step1_report 없이 나머지 태스크만 실행하는 Crew를 빌드한다.
        (2-stage 실행의 Stage 1: verdict 추출 후 final_report 별도 실행)
        
        Args:
            include_revision: True면 revision 태스크 포함
            show_progress: True면 진행 상황 표시
            external_callback: API 연동용 외부 콜백 함수
        """
        manager, workers = self.create_agents()

        if include_revision:
            task_order = [
                "discover_competitors",
                "compact_competitors",
                "analyze_channels",
                "extract_value_props",
                "summarize_channels_vp",
                "mine_gaps",
                "summarize_research",
                "create_pov_and_positioning",
                "red_team_review",
                "revise_positioning",
                "red_team_recheck",
                # final_step1_report 제외!
            ]
        else:
            task_order = [
                "discover_competitors",
                "compact_competitors",
                "analyze_channels",
                "extract_value_props",
                "summarize_channels_vp",
                "mine_gaps",
                "summarize_research",
                "create_pov_and_positioning",
                "red_team_review",
                # final_step1_report 제외!
            ]

        tasks = self.create_tasks(workers, manager, allowed_task_ids=task_order)

        missing = [t for t in task_order if t not in tasks]
        if missing:
            raise KeyError(f"task_order contains unknown task ids: {missing}")

        # Pass 1: 5~70%
        tracker = ProgressTracker(task_order, include_revision, external_callback=external_callback, stage="pass1") if show_progress else None
        step_callback = _make_step_callback(tracker) if tracker else None
        task_callback = _make_task_callback(tracker) if tracker else None

        crew = Crew(
            agents=list(workers.values()),
            tasks=[tasks[t] for t in task_order],
            process=Process.sequential,
            verbose=True,
            step_callback=step_callback,
            task_callback=task_callback,
        )
        
        return crew, tracker

    def build_final_report_only(
        self,
        show_progress: bool = False,
    ) -> Tuple[Crew, Optional["ProgressTracker"]]:
        """
        final_step1_report만 실행하는 Crew를 빌드한다.
        (2-stage 실행의 Stage 2: verdict를 inputs로 받아서 리포트 생성)
        
        주의: inputs에 아래 필드가 필요함:
            - landing_gate_verdict: "LANDING_GO" | "LANDING_HOLD" | "LANDING_NO"
            - research_summary: 리서치 요약 (stage 1에서 저장된 것)
            - gap_hypotheses: 빈틈 가설 (stage 1에서 저장된 것)
            - (revision 시) previous_positioning_output, previous_red_team_output
        """
        manager, workers = self.create_agents()
        
        task_order = ["final_step1_report"]
        
        # final_step1_report만 생성 (context 필터링으로 빈 context가 됨)
        tasks = self.create_tasks(workers, manager, allowed_task_ids=task_order)
        
        # Final Report: 85~100%
        tracker = ProgressTracker(task_order, stage="final_report") if show_progress else None
        step_callback = _make_step_callback(tracker) if tracker else None
        task_callback = _make_task_callback(tracker) if tracker else None

        crew = Crew(
            agents=list(workers.values()),
            tasks=[tasks[t] for t in task_order],
            process=Process.sequential,
            verbose=True,
            step_callback=step_callback,
            task_callback=task_callback,
        )
        
        return crew, tracker


def kickoff_step1(
    inputs: Dict[str, Any], 
    include_revision: bool = False,
    show_progress: bool = True,
) -> str:
    """
    STEP1 Crew를 실행하는 헬퍼 함수.
    
    Args:
        inputs: 입력 데이터
        include_revision: True면 revision 태스크 포함
        show_progress: True면 진행 상황 표시
    """
    crew, tracker = Step1CrewFactory().build(
        include_revision=include_revision,
        show_progress=show_progress,
    )
    
    if tracker:
        tracker.print_header()
        # 첫 번째 태스크 시작 알림
        if tracker.task_order:
            tracker.on_task_start(tracker.task_order[0])
    
    result = crew.kickoff(inputs=inputs)
    
    if tracker:
        tracker.print_summary()
    
    return str(result)


if __name__ == "__main__":
    sample_inputs = {
        "idea_one_liner": "AI가 고객 인터뷰 요약을 자동으로 만들고, 핵심 인사이트를 태깅해주는 툴",
        "target_customer": "초기 창업가/PM",
        "problem_statement": "고객 인터뷰를 많이 해도 정리/인사이트 도출에 시간이 너무 오래 걸린다",
        "current_alternatives": "Notion 정리, Google Docs, Dovetail, 직접 엑셀 태깅",
        "geo_market": "KR",
        "business_type": "B2B",
        "constraints": "광고비 월 30만원 이하, 2주 내 MVP",
        "success_definition": "경쟁사 대비 명확한 POV 1개 + 특정 세그먼트에서 강한 가치",
    }

    print(kickoff_step1(sample_inputs))
