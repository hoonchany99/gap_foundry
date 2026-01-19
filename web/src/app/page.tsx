import { IdeaForm } from '@/components/idea-form';

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-zinc-950 via-zinc-900 to-violet-950">
      {/* 배경 효과 */}
      <div className="fixed inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-violet-900/20 via-transparent to-transparent pointer-events-none" />
      <div className="fixed inset-0 bg-[url('/grid.svg')] opacity-5 pointer-events-none" />
      
      <div className="relative z-10 container mx-auto px-4 py-12 max-w-3xl">
        {/* 헤더 */}
        <header className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 mb-6">
            <span className="text-violet-400 text-sm font-medium">AI-Powered Market Validation</span>
          </div>
          
          <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-white via-violet-200 to-fuchsia-200 bg-clip-text text-transparent">
            Gap Foundry
          </h1>
          
          <p className="text-xl text-zinc-400 max-w-xl mx-auto leading-relaxed">
            아이디어에 시간과 비용을 투자할 가치가 있는지<br />
            <span className="text-violet-400 font-medium">AI가 검증해드립니다</span>
          </p>
        </header>

        {/* 프로세스 안내 */}
        <div className="grid grid-cols-4 gap-2 mb-10 text-center">
          {[
            { step: '1', label: 'PreGate', desc: '입력 체크' },
            { step: '2', label: 'Research', desc: '경쟁 분석' },
            { step: '3', label: 'Red Team', desc: '반증 검토' },
            { step: '4', label: 'Verdict', desc: 'GO/HOLD/NO' },
          ].map((item, i) => (
            <div key={i} className="relative">
              <div className="w-10 h-10 mx-auto rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-sm font-bold text-violet-400 mb-2">
                {item.step}
              </div>
              <p className="text-xs font-medium text-white">{item.label}</p>
              <p className="text-[10px] text-zinc-500">{item.desc}</p>
              {i < 3 && (
                <div className="absolute top-5 left-[60%] w-[80%] h-px bg-gradient-to-r from-zinc-700 to-transparent" />
              )}
            </div>
          ))}
        </div>

        {/* 메인 폼 카드 */}
        <div className="bg-zinc-900/80 backdrop-blur-sm border border-zinc-800 rounded-2xl p-8 shadow-2xl shadow-violet-500/5">
          <IdeaForm />
        </div>

        {/* 푸터 */}
        <footer className="mt-12 text-center text-sm text-zinc-600">
          <p>
            Powered by <span className="text-violet-500">CrewAI</span> + <span className="text-fuchsia-500">GPT-4o</span>
          </p>
          <p className="mt-1">
            검증 1회당 약 $0.50~$1.50 소요
          </p>
        </footer>
      </div>
    </main>
  );
}
