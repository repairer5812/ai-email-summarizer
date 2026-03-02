import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-12 px-6 py-14 md:px-10">
        <section className="grid gap-8 rounded-2xl border border-slate-200 bg-white p-8 shadow-sm md:grid-cols-2 md:p-12">
          <div className="space-y-5">
            <Badge variant="secondary">Windows 로컬 앱</Badge>
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 md:text-5xl">
              받은 메일함,
              <br />
              읽기 쉬운 요약으로.
            </h1>
            <p className="text-base leading-7 text-slate-600 md:text-lg">
              webmail-summary는 메일을 자동으로 수집하고 핵심만 정리해 보여줍니다.
              설치 후 몇 단계 설정만 하면 바로 사용할 수 있습니다.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg">
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer/releases/latest"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  최신 버전 다운로드
                </a>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  GitHub 보기
                </a>
              </Button>
            </div>
          </div>
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>3분 시작 가이드</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-600">
              <p>1) 설치 파일 다운로드 후 실행</p>
              <p>2) /setup에서 메일 연결 테스트</p>
              <p>3) 동기화 시작 후 날짜별 요약 확인</p>
              <p className="pt-2 text-xs text-slate-500">
                업데이트는 대시보드 우측 상단 버전 영역에서 바로 확인할 수 있습니다.
              </p>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">쉬운 설치</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              Python을 따로 몰라도 설치 파일로 바로 시작할 수 있도록 구성합니다.
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">로컬 중심 보안</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              메일 원문은 로컬에 보관되고, API 키는 Windows Credential Manager를 사용합니다.
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">지속 업데이트</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              GitHub Releases 기반으로 최신 버전을 확인하고 안전하게 업데이트합니다.
            </CardContent>
          </Card>
        </section>
      </main>
    </div>
  );
}
