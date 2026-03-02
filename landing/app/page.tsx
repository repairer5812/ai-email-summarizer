import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 via-slate-50 to-white">
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-12 px-6 py-14 md:px-10">
        <section className="grid gap-8 rounded-2xl border border-blue-100 bg-white/95 p-8 shadow-sm md:grid-cols-2 md:p-12">
          <div className="space-y-5">
            <Badge className="bg-blue-100 text-blue-800 hover:bg-blue-100">
              Windows에서 바로 시작
            </Badge>
            <h1 className="text-4xl font-bold tracking-tight text-slate-900 md:text-5xl">
              받은 메일함,
              <br />
              읽기 쉬운 요약으로.
            </h1>
            <p className="text-base leading-7 text-slate-600 md:text-lg">
              webmail-summary는 복잡한 메일을 자동으로 모아,
              중요한 내용만 빠르게 보여줍니다.
              어려운 설정 없이 안내대로 몇 단계만 진행하면 바로 사용할 수 있습니다.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg" className="bg-blue-600 hover:bg-blue-700">
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer/releases/latest"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  무료로 다운로드
                </a>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  설치 파일 목록 보기
                </a>
              </Button>
            </div>
          </div>
          <Card className="border-blue-100 bg-blue-50/40">
            <CardHeader>
              <CardTitle className="text-blue-900">3분 시작 가이드</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-slate-700">
              <p>1) 설치 파일 다운로드 후 실행</p>
              <p>2) 화면 안내에 따라 메일 계정 연결</p>
              <p>3) 동기화 시작 후 날짜별 요약 확인</p>
              <p className="pt-2 text-xs text-slate-600">
                새 버전은 대시보드 우측 상단에서 쉽게 확인하고 업데이트할 수 있습니다.
              </p>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <Card className="border-blue-100">
            <CardHeader>
              <CardTitle className="text-base text-blue-900">쉬운 설치</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              설치 파일을 실행하고 안내를 따라가면 누구나 바로 사용할 수 있습니다.
            </CardContent>
          </Card>
          <Card className="border-blue-100">
            <CardHeader>
              <CardTitle className="text-base text-blue-900">안심 사용</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              메일 원문은 내 PC에 보관되고, 민감한 키는 Windows 보안 저장소를 사용합니다.
            </CardContent>
          </Card>
          <Card className="border-blue-100">
            <CardHeader>
              <CardTitle className="text-base text-blue-900">지속 업데이트</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-600">
              최신 버전을 쉽게 확인하고 필요한 때 안전하게 업데이트할 수 있습니다.
            </CardContent>
          </Card>
        </section>

        <section className="rounded-2xl border border-blue-100 bg-white p-6 text-sm text-slate-700 shadow-sm">
          <p className="font-semibold text-slate-900">개발자</p>
          <p className="mt-2">최경찬</p>
          <p className="mt-1">
            문의: <a className="text-blue-700 underline" href="mailto:repairer5812@gmail.com">repairer5812@gmail.com</a>
          </p>
        </section>
      </main>
    </div>
  );
}
