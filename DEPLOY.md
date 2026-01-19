# 🚀 Gap Foundry 배포 가이드

## 아키텍처

```
┌─────────────────────┐     ┌─────────────────────┐
│   Vercel (Frontend) │────▶│  Railway (Backend)  │
│   Next.js App       │     │  FastAPI + CrewAI   │
└─────────────────────┘     └─────────────────────┘
        │                           │
        │                           ▼
        │                   ┌─────────────────┐
        │                   │   OpenAI API    │
        │                   │   Serper API    │
        │                   └─────────────────┘
        ▼
   사용자 브라우저
```

---

## 1️⃣ 백엔드 배포 (Railway 추천)

### Railway 배포 방법

1. **Railway 계정 생성**: https://railway.app

2. **프로젝트 생성**:
   ```bash
   # Railway CLI 설치 (선택)
   npm install -g @railway/cli
   railway login
   
   # 또는 GitHub 연동으로 자동 배포
   ```

3. **GitHub 연동**:
   - Railway Dashboard → New Project → Deploy from GitHub
   - `gap_foundry` 리포지토리 선택

4. **환경 변수 설정** (Railway Dashboard → Variables):
   ```
   OPENAI_API_KEY=sk-xxxxxxxxxxxxx
   SERPER_API_KEY=xxxxxxxxxxxxx
   CORS_ORIGINS=https://your-frontend.vercel.app
   ```

5. **배포 확인**:
   - Railway가 자동으로 Dockerfile을 감지하고 빌드
   - 배포 완료 후 URL 확인 (예: `https://gap-foundry-backend.up.railway.app`)

---

## 2️⃣ 프론트엔드 배포 (Vercel)

### Vercel 배포 방법

1. **Vercel 계정 생성**: https://vercel.com

2. **프로젝트 연결**:
   ```bash
   # Vercel CLI 설치
   npm install -g vercel
   
   # web 폴더에서 실행
   cd web
   vercel
   ```

3. **또는 GitHub 연동**:
   - Vercel Dashboard → Add New Project → Import Git Repository
   - `gap_foundry` 리포지토리 선택
   - **Root Directory**: `web` 설정 중요!

4. **환경 변수 설정** (Vercel Dashboard → Settings → Environment Variables):
   ```
   NEXT_PUBLIC_API_URL=https://your-backend.railway.app
   ```

5. **배포 확인**:
   - Vercel이 자동으로 Next.js 앱 빌드
   - 배포 완료 후 URL 확인 (예: `https://gap-foundry.vercel.app`)

---

## 3️⃣ 배포 후 설정

### Railway 환경 변수 업데이트
```
CORS_ORIGINS=https://gap-foundry.vercel.app
```

### Vercel 환경 변수 업데이트
```
NEXT_PUBLIC_API_URL=https://gap-foundry-backend.up.railway.app
```

---

## 🔧 트러블슈팅

### CORS 에러
- Railway의 `CORS_ORIGINS` 환경변수에 Vercel 도메인 추가
- 쉼표로 여러 도메인 구분: `https://domain1.vercel.app,https://domain2.vercel.app`

### 타임아웃 에러
- Railway의 기본 요청 타임아웃은 충분히 길지만, CrewAI 실행이 10분 이상 걸릴 수 있음
- SSE 연결로 실시간 상태 업데이트 제공

### 빌드 실패
- Python 버전: 3.11 이상 필요
- Node.js 버전: 18 이상 필요

---

## 💰 예상 비용

### Railway (백엔드)
- Free Tier: $5 크레딧/월 (약 500시간 실행)
- Hobby: $5/월부터

### Vercel (프론트엔드)
- Free Tier: 충분한 대역폭과 빌드 포함
- Pro: $20/월 (팀 기능 필요 시)

### API 비용
- OpenAI: 실행당 ~$0.15-0.25
- Serper: 무료 2,500회/월

---

## 📝 체크리스트

- [ ] Railway 백엔드 배포
- [ ] Railway 환경 변수 설정 (OPENAI_API_KEY, SERPER_API_KEY, CORS_ORIGINS)
- [ ] Vercel 프론트엔드 배포
- [ ] Vercel 환경 변수 설정 (NEXT_PUBLIC_API_URL)
- [ ] CORS 도메인 상호 연결 확인
- [ ] 실제 아이디어 검증 테스트
