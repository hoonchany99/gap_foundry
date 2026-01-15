# 🔍 Gap Foundry

> **창업 아이디어 시장검증을 AI가 자동으로 해주는 도구**

"이 아이디어 해볼까?" 고민될 때, 경쟁사 분석부터 포지셔닝까지 **15~25분 만에** 자동으로 검증해줍니다.

---

## 🎯 이런 분들께 추천해요

- 💡 **창업 아이디어가 있는데**, 시장조사하기 귀찮은 분
- 🤔 **"이거 진짜 되나?"** 빠르게 확인하고 싶은 분  
- 📊 **경쟁사 분석**을 체계적으로 하고 싶은 PM/기획자
- ⏰ 시간은 없는데 **Go/No-Go 판단**이 필요한 분

---

## ✨ 뭘 해주나요?

| 단계 | 하는 일 | 결과물 |
|------|---------|--------|
| 1️⃣ | **경쟁사 발굴** | 직접/간접 경쟁사 15개+ 리스트 |
| 2️⃣ | **채널/메시지 분석** | 경쟁사들이 어디서 뭐라고 말하는지 |
| 3️⃣ | **가치제안 분석** | 경쟁사들의 핵심 약속/USP |
| 4️⃣ | **빈틈 발굴** | 시장에서 아직 안 채워진 기회 |
| 5️⃣ | **포지셔닝 설계** | 우리만의 관점(POV) + 차별화 전략 |
| 6️⃣ | **레드팀 검토** | 날카로운 반증 + PASS/FAIL 판정 |
| 7️⃣ | **최종 리포트** | Go/No-Go 결론 + 다음 액션 |

---

## 🚀 시작하기 (5분)

### 1. 필요한 것

- Python 3.10 이상
- OpenAI API 키 ([여기서 발급](https://platform.openai.com/api-keys))
- Serper API 키 ([여기서 발급](https://serper.dev/) - 무료 2,500회)

### 2. 설치

```bash
# 프로젝트 다운로드
git clone https://github.com/your-repo/gap_foundry.git
cd gap_foundry

# 의존성 설치
pip install -e .
```

### 3. API 키 설정

`.env` 파일을 만들고 아래 내용을 입력하세요:

```bash
OPENAI_API_KEY=sk-xxxxxxxxxxxxx
SERPER_API_KEY=xxxxxxxxxxxxx
```

---

## 📖 사용법

### 🔰 가장 쉬운 방법: 대화형 인터뷰

```bash
python3 -m gap_foundry.main --refine
```

**AI가 인터뷰어처럼 아이디어를 이해하려고 노력합니다:**

```
🎯 Gap Foundry - 아이디어 인터뷰
════════════════════════════════════════════════════════════
아이디어를 자유롭게 이야기해주세요.
저는 먼저 이해하려고 노력할게요 😊

📝 입력: 의사가 환자를 관리하는 CRM 서비스

🤖 아, 의사가 환자 한 분 한 분의 건강 상태뿐 아니라 개인적인 취향이나 
   성향까지 고려해서 더 맞춤형으로 케어할 수 있는 시스템이군요! 
   혹시 이 아이디어는 직접 경험에서 나온 건가요? 🤔

📝 입력: 응 난 치과의사야

──────────────────────────────────────────────────────────
✅ 아이디어가 충분히 이해됐어요!
──────────────────────────────────────────────────────────

📝 입력: done

📋 시장 검증 INPUT 최종 확인
════════════════════════════════════════════════════════════
💡 아이디어: 의사가 환자를 관리하는 CRM 서비스
👥 타깃 고객: 의사(의료기관 종사자)
🎯 해결할 문제: 환자 성향/취향 파악 어려움
🔄 현재 대안: 기존 CRM (추정)
🌍 시장: KR
💼 비즈니스 유형: B2B
════════════════════════════════════════════════════════════
```

**특징:**
- ❌ 직접 질문 안 함 ("타깃 고객이 누구인가요?" 같은)
- ✅ 해석 제안 ("~인 것 같아요. 맞나요?")
- ✅ 종료 시점은 사용자가 결정 (`done`)
- ✅ 마지막에 수정 가능

---

### 📝 CLI로 바로 실행

```bash
python3 -m gap_foundry.main \
  --idea "고객 인터뷰 자동 요약 툴" \
  --target "초기 창업가/PM" \
  --problem "인터뷰 정리에 시간이 너무 오래 걸린다" \
  --alternatives "Notion, Google Docs, Dovetail, 엑셀" \
  --geo KR \
  --type B2B \
  --out outputs/my_report.md
```

### 📁 JSON 파일로 실행

`input.json` 파일 생성:

```json
{
  "idea_one_liner": "고객 인터뷰 자동 요약 툴",
  "target_customer": "초기 창업가/PM",
  "problem_statement": "인터뷰 정리에 시간이 너무 오래 걸린다",
  "current_alternatives": "Notion, Google Docs, Dovetail, 엑셀",
  "geo_market": "KR",
  "business_type": "B2B"
}
```

```bash
python3 -m gap_foundry.main --input input.json
```

---

## 🔄 자동 수정 모드 (--auto-revise)

레드팀이 **FAIL** 판정을 내리면, **Revision-only**로 효율적으로 재검토합니다:

```bash
python3 -m gap_foundry.main --refine --auto-revise
```

### Revision-only 플로우

```
┌─────────────────────────────────────────────────────────────────┐
│ Pass 1: 전체 실행                                               │
│   경쟁사 → 채널 → VP → 빈틈 → POV → Red Team → Report           │
├─────────────────────────────────────────────────────────────────┤
│                       VERDICT 확인                              │
│                           │                                     │
│              ┌────────────┴────────────┐                        │
│              ▼                         ▼                        │
│           PASS                       FAIL                       │
│             │                          │                        │
│             ▼                          ▼                        │
│         바로 완료            Pass 2: Revision-only 🚀           │
│                              (3개 태스크만!)                    │
│                              ├── revise_positioning             │
│                              ├── red_team_recheck               │
│                              └── final_report                   │
└─────────────────────────────────────────────────────────────────┘
```

**💰 비용 최적화:** Pass 2에서 경쟁사 리서치를 다시 하지 않고, **포지셔닝 수정만** 수행!

```
🔍 Red Team Verdict: FAIL
❌ FAIL! Revision-only 실행을 시작합니다...
   (revision 태스크 3개만 실행: revise → recheck → report)

🔍 Red Team Recheck Verdict: PASS
✅ 수정 후 통과!
```

---

## 💬 후속 대화 모드 (--chat)

리포트가 나온 후, **리포트에 대해 질문하거나 반론(Claim)**을 제기할 수 있습니다:

```bash
python3 -m gap_foundry.main --refine --chat
```

### 사용 예시

```
✅ Final report saved to: outputs/reports/...

============================================================
💬 리포트 후속 대화 모드
============================================================
리포트에 대해 궁금한 점이나 반론이 있으면 자유롭게 말씀하세요.
종료하려면 'quit', 'exit', 또는 '종료'를 입력하세요.
============================================================

📝 나: 근데 경쟁사 분석에서 A회사가 빠진 것 같은데?

🤖 AI: 좋은 지적이에요! 말씀하신 A회사를 확인해보니, 실제로 우리 타깃 세그먼트와
   직접 경쟁 관계에 있을 수 있습니다. 다만 이번 분석에서는 '검색 기반'으로 
   발굴했기 때문에 SEO/광고 노출이 적은 경쟁사는 누락될 수 있어요.
   
   A회사의 핵심 가치제안이 무엇인지 알려주시면, 현재 POV와 어떻게 
   차별화되는지 비교 분석해드릴게요.

📝 나: 난 오히려 B2C가 아니라 B2B로 가야 한다고 생각해

🤖 AI: 흥미로운 관점이네요! B2B로 피봇하면 다음과 같은 장단점이 있습니다:

   ✅ 장점:
   - 고객 획득 비용(CAC)이 낮을 수 있음
   - 계약 단위가 크고 안정적
   
   ⚠️ 고려사항:
   - 기존 경쟁 구도가 완전히 달라짐
   - 영업 사이클이 길어질 수 있음
   
   만약 B2B로 전환한다면, 타깃을 '중소기업 마케터'에서 '에이전시'로 
   바꾸는 것도 검토해볼 만합니다.

📝 나: 종료
대화를 종료합니다. 감사합니다! 👋
```

**특징:**
- 🎯 리포트 내용을 컨텍스트로 사용
- 💡 반론을 인정하고 새로운 시각 제시
- 🔄 대화 히스토리 유지 (이전 내용 기억)

---

## 📊 결과물

실행 후 `outputs/` 폴더에 저장됩니다:

```
outputs/
├── reports/                                    # 📋 최종 리포트 모음
│   ├── 2026-01-16_1430_AI이력서자동작성_B2C_report.md
│   └── 2026-01-16_1545_환자관리CRM_B2B_report.md
│
└── runs/                                       # 📂 실행별 상세 결과
    └── 2026-01-16_1430_환자관리CRM_B2B/
        ├── 01_경쟁사_발굴.md      # 🔍 경쟁사 15개 발굴
        ├── 02_경쟁사_압축.md      # 📦 상위 8개로 압축
        ├── 03_채널_분석.md        # 📢 마케팅 채널 분석
        ├── 04_가치제안_추출.md    # 💎 VP/USP 추출
        ├── 05_채널VP_요약.md      # 📋 압축 요약
        ├── 06_빈틈_발굴.md        # 🕳️ Gap Hypotheses
        ├── 07_리서치_요약.md      # 📑 전체 리서치 요약
        ├── 08_POV_포지셔닝.md     # 🎯 POV & 포지셔닝
        ├── 09_레드팀_검토.md      # 🔴 Red Team Review
        ├── 12_최종_리포트.md      # 📊 최종 리포트
        ├── _index.json           # 파일 인덱스
        └── _usage_metrics.json   # 💰 비용 정보
```

### 파일명 규칙

| 폴더/파일 | 설명 |
|----------|------|
| `reports/` | 최종 리포트만 모아둔 폴더 (빠른 조회용) |
| `runs/` | 실행별 전체 결과 (디버깅/상세 분석용) |
| `YYYY-MM-DD_HHMM_아이디어_타입/` | 실행 폴더명 |

---

## 💰 비용 안내

| 모드 | 예상 비용 | 소요 시간 |
|------|----------|----------|
| 기본 실행 | ~$0.80 | 15~25분 |
| Auto-Revise (FAIL 시) | ~$0.90 | +3~5분 |

> 💡 Revision-only 덕분에 FAIL 시 추가 비용이 적습니다!

비용은 `_usage_metrics.json`에서 확인할 수 있어요.

---

## 🛠️ 옵션 정리

| 옵션 | 설명 | 예시 |
|------|------|------|
| `--refine` | 대화형 입력 (AI 인터뷰어) | `--refine` |
| `--input` | JSON 파일로 입력 | `--input input.json` |
| `--idea` | 아이디어 한 줄 | `--idea "요약 툴"` |
| `--target` | 타깃 고객 | `--target "PM"` |
| `--problem` | 해결할 문제 | `--problem "시간이 오래 걸림"` |
| `--alternatives` | 현재 대안들 | `--alternatives "Notion, Docs"` |
| `--geo` | 지역 (KR/US/Global) | `--geo KR` |
| `--type` | B2B/B2C/B2B2C | `--type B2B` |
| `--out` | 결과 저장 경로 | `--out report.md` |
| `--auto-revise` | FAIL 시 자동 수정 | `--auto-revise` |
| `--chat` | 리포트 후 대화 모드 | `--chat` |
| `--dry-run` | 실행 없이 설정 확인 | `--dry-run` |
| `--safe-mode` | 운영급 안전 모드 | `--safe-mode` |

---

## 🏗️ 아키텍처

### 전체 플로우

```
┌─────────────────────────────────────────────────────────────────┐
│                        Gap Foundry                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [입력]  ──→  [8개 AI 에이전트]  ──→  [최종 리포트]             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │  🔍 경쟁사 발굴 ──→ 📦 압축 ──→ 📢 채널 분석           │   │
│  │                              ↘                         │   │
│  │                                📋 채널VP 요약          │   │
│  │                              ↙                         │   │
│  │  💎 VP 추출 ──────────────→ 🕳️ 빈틈 발굴              │   │
│  │                                   ↓                    │   │
│  │                              📑 리서치 요약            │   │
│  │                                   ↓                    │   │
│  │                              🎯 POV/포지셔닝           │   │
│  │                                   ↓                    │   │
│  │                              🔴 레드팀 검토            │   │
│  │                                   ↓                    │   │
│  │                              📊 최종 리포트            │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  FAIL 시 → ✏️ 포지셔닝 수정 → 🔴 재검토 → 📊 최종 리포트      │
│            (Revision-only: 3개 태스크만!)                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### AI 에이전트 구성

| 에이전트 | 역할 | LLM |
|----------|------|-----|
| 🔍 **Competitor Discovery** | 경쟁사/대체재 발굴 | gpt-4.1-mini |
| 📢 **Channel Intel** | 채널/메시지 분석 | gpt-4.1-mini |
| 💎 **VP Extractor** | 가치제안 추출 | gpt-4.1-mini |
| 📋 **Research Summarizer** | 리서치 요약/압축 | gpt-4.1-mini |
| 🕳️ **Gap Miner** | 빈틈 가설 도출 | **gpt-4.1** |
| 🎯 **POV Strategist** | 포지셔닝 설계 | gpt-4.1-mini |
| 🔴 **Red Team** | 날카로운 반증 | **gpt-4.1** |
| 🎭 **Orchestrator** | 전체 조율 | **gpt-4.1** |

### LLM 배치 전략

```
┌─────────────────────────────────────────────────────────────┐
│                     LLM 배치 전략                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🧠 gpt-4.1 (Main)         ⚡ gpt-4.1-mini (Fast)          │
│  ─────────────────         ────────────────────            │
│  • Orchestrator            • Competitor Discovery          │
│  • Gap Miner               • Channel Intel                 │
│  • Red Team                • VP Extractor                  │
│                            • Research Summarizer           │
│  → 판단/창의/반증          • POV Strategist                │
│    품질이 중요한 곳                                        │
│                            → 검색/정리/구조화              │
│                              속도가 중요한 곳              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 핵심 설계 원칙

| 원칙 | 설명 |
|------|------|
| **Sequential Process** | 각 Task가 자신의 context만 참조 (TPM 안전) |
| **Context 압축** | `summarize_research`, `summarize_channels_vp`가 정보 압축 |
| **Tool 하드리밋** | 웹 스크래핑 800자, 검색 1800자 제한 |
| **Revision-only** | FAIL 시 전체 재실행 ❌ → 포지셔닝만 수정 ✅ |
| **역할 분리** | Red Team은 새로운 조사 금지, 비판만 |

---

## ⚙️ 환경변수

`.env` 파일에 설정:

```bash
# 필수
OPENAI_API_KEY=sk-xxxxxxxxxxxxx
SERPER_API_KEY=xxxxxxxxxxxxx

# 선택 (기본값 있음)
MAIN_LLM_MODEL=gpt-4.1        # 기본: gpt-4.1
FAST_LLM_MODEL=gpt-4.1-mini   # 기본: gpt-4.1-mini
```

---

## ❓ FAQ

### Q: API 키는 어디서 발급받나요?

- **OpenAI**: https://platform.openai.com/api-keys
- **Serper** (웹 검색용): https://serper.dev/ (무료 2,500회)

### Q: 비용이 얼마나 드나요?

1회 실행당 약 **$0.80** (한화 1,000원 정도). `_usage_metrics.json`에서 정확한 비용 확인 가능.

### Q: FAIL이 나오면 어떻게 하나요?

1. **리포트의 Salvage Options 확인** - 다른 방향 제안이 있어요
2. **`--auto-revise` 사용** - 자동으로 수정 후 재검토
3. **아이디어 변경** - FAIL은 "지금 형태"가 안 되는 거지, 문제 자체가 틀린 게 아니에요

### Q: 검색이 안 되는 것 같아요

`SERPER_API_KEY` 설정을 확인하세요. 없으면 AI가 "추측"으로 분석합니다 (품질 저하).

### Q: 입력 필드를 다 채워야 하나요?

**6개 핵심 필드만 필요합니다:**
- idea_one_liner, target_customer, problem_statement
- current_alternatives, geo_market, business_type

`constraints`와 `success_definition`은 선택사항이며 기본값이 적용됩니다.

---

## 🔧 기술 스택

- **Framework**: [CrewAI](https://docs.crewai.com/) (Multi-Agent Orchestration)
- **LLM**: OpenAI GPT-4.1 / GPT-4.1-mini
- **Search**: [Serper](https://serper.dev/) (Google Search API)
- **Process**: Sequential (TPM 안전, 누적 메모리 문제 해결)

---

## 🤝 문의

이슈나 피드백은 GitHub Issues에 남겨주세요!

---

**Made with ❤️ for founders who validate before they build.**
