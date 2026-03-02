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
              메일 정리 시간,
              <br />
              오늘부터 줄여드립니다.
            </h1>
            <p className="text-base leading-7 text-slate-600 md:text-lg">
              복잡한 메일을 일일이 읽지 않아도,
              핵심만 빠르게 확인할 수 있도록 도와주는 Windows 앱입니다.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild size="lg" className="bg-blue-600 hover:bg-blue-700">
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer/releases/latest/download/webmail-summary.exe"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  바로 설치하기 (.exe)
                </a>
              </Button>
              <Button variant="outline" size="lg" asChild>
                <a
                  href="https://github.com/repairer5812/ai-email-summarizer/releases/latest/download/webmail-summary-windows-x64.zip"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  압축 파일 받기 (.zip)
                </a>
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              보통은 <span className="font-semibold text-slate-700">.exe</span>를 받으면 됩니다.
              압축 파일이 필요할 때만 <span className="font-semibold text-slate-700">.zip</span>을 선택하세요.
            </p>
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

        <section className="space-y-4">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">이런 문제를 해결합니다</h2>
          <div className="grid gap-4 md:grid-cols-3">
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">메일이 너무 많아 놓침</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">
                중요한 메일이 일반 메일 사이에 묻혀서 확인이 늦어지는 문제를 줄입니다.
              </CardContent>
            </Card>
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">읽느라 시간이 오래 걸림</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">
                핵심 요약 중심으로 먼저 보여줘서 메일 처리 시간을 단축할 수 있습니다.
              </CardContent>
            </Card>
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">미루다가 누락 위험</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">
                날짜별로 정리된 화면으로 오늘 처리할 메일부터 빠르게 확인할 수 있습니다.
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">왜 믿고 써도 되나요?</h2>
          <div className="grid gap-4 md:grid-cols-3">
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
                <CardTitle className="text-base text-blue-900">로컬 중심 보안</CardTitle>
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
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">사용 방법은 단 3단계</h2>
          <div className="grid gap-4 md:grid-cols-3">
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">1. 설치하기</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">`.exe` 파일을 다운로드해서 실행합니다.</CardContent>
            </Card>
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">2. 메일 연결하기</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">`/setup`에서 메일 계정을 연결하고 테스트합니다.</CardContent>
            </Card>
            <Card className="border-blue-100">
              <CardHeader>
                <CardTitle className="text-base text-blue-900">3. 요약 확인하기</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-slate-600">동기화 시작 후 날짜별 요약 화면에서 바로 확인합니다.</CardContent>
            </Card>
          </div>
        </section>

        <section className="rounded-2xl border border-blue-200 bg-blue-50/50 p-8 text-center shadow-sm">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900">아직 망설여진다면, 설치 가이드부터 확인하세요</h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            바로 설치가 부담되면 사용 방법을 먼저 확인한 뒤 시작해도 됩니다.
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Button asChild className="bg-blue-600 hover:bg-blue-700">
              <a
                href="https://github.com/repairer5812/ai-email-summarizer#일반-사용자용-안내-먼저-읽어주세요"
                target="_blank"
                rel="noopener noreferrer"
              >
                설치 가이드 먼저 보기
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a
                href="https://github.com/repairer5812/ai-email-summarizer/releases/latest"
                target="_blank"
                rel="noopener noreferrer"
              >
                전체 다운로드 목록 보기
              </a>
            </Button>
          </div>
        </section>

        <section className="rounded-2xl border border-blue-100 bg-white p-6 text-sm text-slate-700 shadow-sm">
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
