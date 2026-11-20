import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "EDGE-FIRE 개인 통합", description: "저장공간과 AI 영상 분석" };
export default function RootLayout({children}: {children: React.ReactNode}) { return <html lang="ko"><body>{children}</body></html>; }
