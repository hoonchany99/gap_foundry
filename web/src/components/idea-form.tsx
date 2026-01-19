'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { checkPreGate, submitValidation, type ValidationRequest, type PreGateResponse } from '@/lib/api';

// 디바운스 훅
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

export function IdeaForm() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [preGateResult, setPreGateResult] = useState<PreGateResponse | null>(null);
  const [preGateLoading, setPreGateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<ValidationRequest>({
    idea_one_liner: '',
    target_customer: '',
    problem_statement: '',
    current_alternatives: '',
    geo_market: 'KR',
    business_type: 'B2B',
  });

  // 디바운스된 폼 데이터로 PreGate 체크
  const debouncedFormData = useDebounce(formData, 800);

  // PreGate 실시간 체크
  useEffect(() => {
    const shouldCheck = 
      debouncedFormData.idea_one_liner.length >= 5 &&
      debouncedFormData.target_customer.length >= 2 &&
      debouncedFormData.problem_statement.length >= 5;

    if (!shouldCheck) {
      setPreGateResult(null);
      return;
    }

    const runPreGate = async () => {
      setPreGateLoading(true);
      try {
        const result = await checkPreGate({
          idea_one_liner: debouncedFormData.idea_one_liner,
          target_customer: debouncedFormData.target_customer,
          problem_statement: debouncedFormData.problem_statement,
          current_alternatives: debouncedFormData.current_alternatives,
        });
        setPreGateResult(result);
      } catch (e) {
        console.error('PreGate check failed:', e);
      } finally {
        setPreGateLoading(false);
      }
    };

    runPreGate();
  }, [debouncedFormData]);

  const handleInputChange = useCallback((field: keyof ValidationRequest, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    setError(null);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const result = await submitValidation(formData);
      router.push(`/validate/${result.run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청 실패');
      setIsSubmitting(false);
    }
  };

  const scoreColor = preGateResult 
    ? preGateResult.score >= 0.75 ? 'text-emerald-400' 
    : preGateResult.score >= 0.5 ? 'text-amber-400' 
    : 'text-rose-400'
    : '';

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      {/* 핵심 입력 필드들 */}
      <div className="grid gap-6">
        {/* 아이디어 한 줄 */}
        <div className="space-y-2">
          <Label htmlFor="idea" className="text-base font-semibold">
            💡 아이디어 한 줄 요약
          </Label>
          <Textarea
            id="idea"
            placeholder="예: 야근 많은 30대 직장인이 저녁 10시 이후 과식을 줄이게 돕는 앱"
            value={formData.idea_one_liner}
            onChange={(e) => handleInputChange('idea_one_liner', e.target.value)}
            className="min-h-[80px] bg-zinc-900/50 border-zinc-700 focus:border-violet-500 text-white placeholder:text-zinc-500"
            required
          />
          <p className="text-xs text-zinc-500">
            무엇을 만들려고 하는지 한 문장으로 설명해주세요
          </p>
        </div>

        {/* 타깃 고객 */}
        <div className="space-y-2">
          <Label htmlFor="target" className="text-base font-semibold">
            👥 타깃 고객
          </Label>
          <Input
            id="target"
            placeholder="예: 주 3회 이상 야근하는 30대 사무직"
            value={formData.target_customer}
            onChange={(e) => handleInputChange('target_customer', e.target.value)}
            className="bg-zinc-900/50 border-zinc-700 focus:border-violet-500 text-white placeholder:text-zinc-500"
            required
          />
          <p className="text-xs text-zinc-500">
            이 문제를 가장 절실히 느끼는 사람은 누구인가요?
          </p>
        </div>

        {/* 해결하려는 문제 */}
        <div className="space-y-2">
          <Label htmlFor="problem" className="text-base font-semibold">
            🎯 해결하려는 문제
          </Label>
          <Textarea
            id="problem"
            placeholder="예: 늦은 퇴근 후 스트레스 해소로 과식 → 체중 증가 → 다음날 후회 반복"
            value={formData.problem_statement}
            onChange={(e) => handleInputChange('problem_statement', e.target.value)}
            className="min-h-[80px] bg-zinc-900/50 border-zinc-700 focus:border-violet-500 text-white placeholder:text-zinc-500"
            required
          />
          <p className="text-xs text-zinc-500">
            구체적인 상황과 감정을 포함해주세요
          </p>
        </div>

        {/* 현재 대안 */}
        <div className="space-y-2">
          <Label htmlFor="alternatives" className="text-base font-semibold">
            🔄 현재 대안
          </Label>
          <Textarea
            id="alternatives"
            placeholder="예: 다이어트 앱(마이피트니스팔), 의지력, 야식 배달 안 시키기"
            value={formData.current_alternatives}
            onChange={(e) => handleInputChange('current_alternatives', e.target.value)}
            className="min-h-[60px] bg-zinc-900/50 border-zinc-700 focus:border-violet-500 text-white placeholder:text-zinc-500"
            required
          />
          <p className="text-xs text-zinc-500">
            타깃이 지금 이 문제를 어떻게 해결하고 있나요?
          </p>
        </div>

        {/* 부가 옵션 */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="geo" className="text-sm">🌍 목표 시장</Label>
            <Select 
              value={formData.geo_market} 
              onValueChange={(v) => handleInputChange('geo_market', v as any)}
            >
              <SelectTrigger className="bg-zinc-900/50 border-zinc-700 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="KR">🇰🇷 한국</SelectItem>
                <SelectItem value="US">🇺🇸 미국</SelectItem>
                <SelectItem value="Global">🌐 글로벌</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="type" className="text-sm">💼 비즈니스 유형</Label>
            <Select 
              value={formData.business_type} 
              onValueChange={(v) => handleInputChange('business_type', v as any)}
            >
              <SelectTrigger className="bg-zinc-900/50 border-zinc-700 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-700">
                <SelectItem value="B2B">B2B (기업 대상)</SelectItem>
                <SelectItem value="B2C">B2C (소비자 대상)</SelectItem>
                <SelectItem value="B2B2C">B2B2C (혼합)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* PreGate 실시간 피드백 */}
      {(preGateResult || preGateLoading) && (
        <Card className={`border-2 transition-colors ${
          preGateLoading ? 'border-zinc-700 bg-zinc-900/30' :
          preGateResult?.is_valid ? 'border-emerald-500/50 bg-emerald-950/20' :
          'border-rose-500/50 bg-rose-950/20'
        }`}>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg flex items-center gap-2">
                {preGateLoading ? (
                  <>
                    <span className="animate-pulse">🔍</span>
                    <span className="text-zinc-400">입력 검사 중...</span>
                  </>
                ) : preGateResult?.is_valid ? (
                  <>
                    <span>✅</span>
                    <span className="text-emerald-400">검증 준비 완료</span>
                  </>
                ) : (
                  <>
                    <span>⚠️</span>
                    <span className="text-rose-400">입력 구체화 필요</span>
                  </>
                )}
              </CardTitle>
              {preGateResult && (
                <Badge variant="outline" className={`${scoreColor} border-current`}>
                  구체성 {Math.round(preGateResult.score * 100)}%
                </Badge>
              )}
            </div>
          </CardHeader>
          
          {preGateResult && !preGateResult.is_valid && (
            <CardContent className="space-y-3">
              {preGateResult.fail_reasons.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-rose-400 mb-1">❌ 문제점:</p>
                  <ul className="text-sm text-zinc-400 space-y-1">
                    {preGateResult.fail_reasons.map((reason, i) => (
                      <li key={i}>• {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              
              {preGateResult.suggestions.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-amber-400 mb-1">💡 개선 제안:</p>
                  <ul className="text-sm text-zinc-400 space-y-1">
                    {preGateResult.suggestions.map((sug, i) => (
                      <li key={i}>• {sug}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          )}
          
          {preGateResult && preGateResult.warnings.length > 0 && preGateResult.is_valid && (
            <CardContent>
              <p className="text-sm text-amber-400">
                ⚠️ {preGateResult.warnings.join(' | ')}
              </p>
            </CardContent>
          )}
        </Card>
      )}

      {/* 에러 메시지 */}
      {error && (
        <Alert variant="destructive" className="bg-rose-950/50 border-rose-500/50">
          <AlertTitle>오류</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* 제출 버튼 */}
      <Button 
        type="submit" 
        size="lg"
        disabled={isSubmitting || (preGateResult !== null && !preGateResult.is_valid)}
        className="w-full h-14 text-lg font-semibold bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isSubmitting ? (
          <span className="flex items-center gap-2">
            <span className="animate-spin">⏳</span>
            검증 시작 중...
          </span>
        ) : (
          <span className="flex items-center gap-2">
            🚀 아이디어 검증 시작
          </span>
        )}
      </Button>

      <p className="text-center text-sm text-zinc-500">
        AI 기반 경쟁사 리서치 및 시장 검증 분석이 시작됩니다 (약 10-15분 소요)
      </p>
    </form>
  );
}
