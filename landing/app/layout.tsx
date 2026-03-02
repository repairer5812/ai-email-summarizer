import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "webmail-summary | 메일 요약을 더 쉽게",
  description:
    "Windows에서 메일을 자동 수집하고 AI로 요약해주는 webmail-summary 공식 랜딩 페이지입니다.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <head>
        <link rel="preconnect" href="https://cdn.jsdelivr.net" />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css"
        />
      </head>
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
