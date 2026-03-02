import { AnimatedShinyText } from "@/components/ui/animated-shiny-text";
import { BentoGrid } from "@/components/ui/bento-grid";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RetroGrid } from "@/components/ui/retro-grid";
import { ShimmerButton } from "@/components/ui/shimmer-button";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50/70 via-background to-background">
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-14 md:px-10">
        <section className="relative overflow-hidden rounded-3xl border border-border bg-background/50 p-8 shadow-sm backdrop-blur md:p-12">
          <RetroGrid
            className="absolute inset-0"
            lightLineColor="rgba(37,99,235,0.22)"
            darkLineColor="rgba(147,197,253,0.2)"
            opacity={0.4}
            cellSize={56}
            angle={62}
          />

          <div className="relative z-10 grid gap-8 md:grid-cols-[1.25fr_0.75fr] md:items-start">
            <div className="space-y-5">
              <p className="inline-flex rounded-full border border-blue-200 bg-blue-100/70 px-3 py-1 text-sm font-medium text-blue-800">
                Windows 전용 · 로컬 중심 보안
              </p>

              <h1 className="text-4xl font-bold tracking-tight text-slate-900 md:text-5xl">
                <AnimatedShinyText className="mx-0 max-w-none bg-gradient-to-r from-slate-900 via-blue-700 to-slate-900 bg-clip-text text-transparent dark:from-white dark:via-blue-300 dark:to-white">
                  메일함의 노이즈를 끄고, 핵심만 켜다.
                </AnimatedShinyText>
              </h1>

              <p className="max-w-2xl text-base leading-7 text-slate-700 md:text-lg">
                중요한 메일이 일반 메일 사이에 묻히지 않도록.
                내 PC에서 안전하게 작동하는 윈도우 전용 AI 메일 요약 앱.
              </p>

              <div className="flex flex-wrap gap-3">
                <form
                  action="https://github.com/repairer5812/ai-email-summarizer/releases/latest/download/webmail-summary.exe"
                  method="get"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ShimmerButton type="submit" className="h-11 px-7 text-base font-semibold" background="rgb(37 99 235)">
                    무료로 다운로드 (.exe)
                  </ShimmerButton>
                </form>

                <Button variant="outline" size="lg" asChild className="border-blue-200 bg-background/60">
                  <a
                    href="https://github.com/repairer5812/ai-email-summarizer#일반-사용자용-안내-먼저-읽어주세요"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    설치 가이드 보기
                  </a>
                </Button>
              </div>

              <p className="text-sm text-slate-600">
                설치가 가장 쉬운 파일은 <span className="font-semibold text-slate-800">webmail-summary.exe</span>입니다.
              </p>
            </div>

            <Card className="border-border bg-background/60 shadow-sm backdrop-blur">
              <CardHeader>
                <CardTitle className="text-blue-900">3분 시작 가이드</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-base text-slate-700">
                <p>1) 설치 파일 다운로드 후 실행</p>
                <p>2) /setup에서 메일 연결 테스트</p>
                <p>3) 동기화 시작 후 날짜별 요약 확인</p>
                <p>4) 필요하면 대시보드에서 최신 버전 업데이트 확인</p>
                <p className="text-sm text-slate-600">처음 설치부터 첫 요약 확인까지 보통 3분 내외입니다.</p>
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="relative rounded-3xl border border-border bg-background/50 p-6 shadow-sm backdrop-blur md:p-8">
          <div className="mx-auto w-full max-w-4xl animate-[float_6s_ease-in-out_infinite] rounded-2xl border border-blue-100 bg-white/90 p-4 shadow-md">
            <div className="mb-3 flex items-center gap-2">
              <span className="size-2 rounded-full bg-red-300" />
              <span className="size-2 rounded-full bg-amber-300" />
              <span className="size-2 rounded-full bg-emerald-300" />
              <p className="ml-2 text-sm text-slate-500">webmail-summary Dashboard Preview</p>
            </div>
            <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-2 rounded-xl border border-blue-100 bg-blue-50/70 p-4">
                <p className="text-sm font-semibold text-blue-800">핵심 요약</p>
                <div className="space-y-2 text-sm text-slate-700">
                  <p className="rounded-md bg-white/90 px-3 py-2">- 오늘 처리 우선 메일 3건 자동 분류</p>
                  <p className="rounded-md bg-white/90 px-3 py-2">- 일정/요청 메일만 먼저 강조 표시</p>
                  <p className="rounded-md bg-white/90 px-3 py-2">- 읽기 전 핵심 3줄 미리보기 제공</p>
                </div>
              </div>
              <div className="space-y-2 rounded-xl border border-blue-100 bg-white p-4">
                <p className="text-sm font-semibold text-slate-800">오늘의 메일 카드</p>
                <div className="space-y-2 text-sm text-slate-600">
                  <p className="rounded-md border border-slate-200 px-3 py-2">2026-03-02 (월) · 18건</p>
                  <p className="rounded-md border border-slate-200 px-3 py-2">중요 일정 포함 메일 4건</p>
                  <p className="rounded-md border border-slate-200 px-3 py-2">업데이트 알림 · 최신 버전 확인</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">핵심 기능</h2>
          <BentoGrid className="grid-cols-1 gap-4 md:auto-rows-[16rem] md:grid-cols-3">
            <Card className="col-span-1 border-border bg-background/50 shadow-sm backdrop-blur md:col-span-2">
              <CardHeader>
                <CardTitle className="text-lg text-blue-900">3분이면 충분한 아침</CardTitle>
              </CardHeader>
              <CardContent className="text-base leading-7 text-slate-700">
                핵심 요약 중심으로 보여주어 매일 아침 메일 처리 시간을 획기적으로 단축합니다.
              </CardContent>
            </Card>

            <Card className="col-span-1 border-border bg-background/50 shadow-sm backdrop-blur">
              <CardHeader>
                <CardTitle className="text-lg text-blue-900">로컬 중심의 강력한 보안</CardTitle>
              </CardHeader>
              <CardContent className="text-base leading-7 text-slate-700">
                메일 원문은 내 PC에만 보관되며, 민감한 키는 Windows 보안 저장소를 사용하여 안전합니다.
              </CardContent>
            </Card>

            <Card className="col-span-1 border-border bg-background/50 shadow-sm backdrop-blur md:col-span-2">
              <CardHeader>
                <CardTitle className="text-lg text-blue-900">놓치는 메일 제로</CardTitle>
              </CardHeader>
              <CardContent className="text-base leading-7 text-slate-700">
                날짜별로 깔끔하게 정리된 대시보드로 오늘 당장 처리할 메일부터 빠르게 확인하세요.
              </CardContent>
            </Card>

            <Card className="col-span-1 border-border bg-background/50 shadow-sm backdrop-blur">
              <CardHeader>
                <CardTitle className="text-lg text-blue-900">누구나 쉬운 3단계 시작</CardTitle>
              </CardHeader>
              <CardContent className="text-base leading-7 text-slate-700">
                복잡한 설정 없이 설치, 계정 연결, 요약 확인으로 바로 이어지는 직관적인 사용성을 제공합니다.
              </CardContent>
            </Card>
          </BentoGrid>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          <Card className="border-border bg-background/60 shadow-sm backdrop-blur">
            <CardHeader>
              <CardTitle className="text-xl text-slate-900">이런 분께 특히 잘 맞습니다</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-base text-slate-700">
              <p>- 출근 후 메일 정리에 30분 이상 쓰는 직장인</p>
              <p>- 중요한 요청 메일을 자주 놓쳐서 불안한 분</p>
              <p>- 메일 내용을 팀 노트(Obsidian)로 정리하고 싶은 분</p>
              <p>- 클라우드 업로드보다 로컬 보관을 선호하는 분</p>
            </CardContent>
          </Card>

          <Card className="border-border bg-background/60 shadow-sm backdrop-blur">
            <CardHeader>
              <CardTitle className="text-xl text-slate-900">자주 묻는 질문</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-base leading-7 text-slate-700">
              <p><span className="font-semibold">Q.</span> 어떤 파일을 받으면 되나요?<br /><span className="text-slate-600">A.</span> 대부분은 <span className="font-semibold">webmail-summary.exe</span> 하나면 충분합니다.</p>
              <p><span className="font-semibold">Q.</span> 메일 원문은 어디에 저장되나요?<br /><span className="text-slate-600">A.</span> 내 PC 로컬 저장소에 보관됩니다.</p>
              <p><span className="font-semibold">Q.</span> API 키는 안전한가요?<br /><span className="text-slate-600">A.</span> Windows Credential Manager를 사용해 저장합니다.</p>
            </CardContent>
          </Card>
        </section>

        <section className="rounded-2xl border border-blue-100 bg-background/60 p-6 text-base text-slate-700 shadow-sm backdrop-blur">
          <p className="font-semibold text-slate-900">개발자 / 문의</p>
          <p className="mt-2">최경찬</p>
          <p className="mt-1">
            이메일: <a className="text-blue-700 underline" href="mailto:repairer5812@gmail.com">repairer5812@gmail.com</a>
          </p>
        </section>
      </main>
    </div>
  );
}
