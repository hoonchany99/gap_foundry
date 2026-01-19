import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Gap Foundry - AI Market Validation",
  description: "AI가 아이디어의 시장 검증 가치를 판단합니다. 경쟁사 분석, 빈틈 발굴, Red Team 검토를 통해 GO/HOLD/NO 판정을 제공합니다.",
  keywords: ["startup", "market validation", "AI", "idea validation", "competitive analysis"],
  authors: [{ name: "Utopify" }],
  openGraph: {
    title: "Gap Foundry - AI Market Validation",
    description: "AI가 아이디어의 시장 검증 가치를 판단합니다",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
