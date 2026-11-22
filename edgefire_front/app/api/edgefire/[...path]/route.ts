import { NextRequest } from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  const relative = path.join('/');
  if (!/^(config|training-status|forecast|jobs(?:\/JOB_[a-f0-9]{32}(?:\/(?:image|retry|annotated|result))?)?)$/.test(relative))
    return Response.json({detail: '경로를 찾을 수 없습니다.'}, {status: 404});
  if (request.method === 'POST' && ![process.env.FRONTEND_BASE_URL || 'http://127.0.0.1:3200',(process.env.FRONTEND_BASE_URL || 'http://127.0.0.1:3200').replace('127.0.0.1','localhost')].includes(request.headers.get('origin') || ''))
    return Response.json({detail: '같은 화면에서 요청해 주세요.'}, {status: 403});
  const token = process.env.LOCAL_API_TOKEN;
  if (!token) return Response.json({detail: '로컬 서버 설정이 필요합니다.'}, {status: 503});
  try {
    let body: Uint8Array | undefined;
    if (request.method === 'POST') {
      const chunks: Uint8Array[] = [];
      let bytes = 0;
      const reader = request.body?.getReader();
      if (reader) {
        while (true) {
          const item = await reader.read();
          if (item.done) break;
          bytes += item.value.byteLength;
          if (bytes > 11*1024*1024) {
            await reader.cancel();
            return Response.json({detail: '이미지는 10MiB 이하로 보내 주세요.'}, {status: 413});
          }
          chunks.push(item.value);
        }
      }
      body = Buffer.concat(chunks);
    }
    const headers: Record<string,string> = {'X-API-Key': token};
    const contentType = request.headers.get('content-type');
    if (contentType) headers['Content-Type'] = contentType;
    const response = await fetch((process.env.BACKEND_BASE_URL || 'http://127.0.0.1:8100')+'/api/v1/storage/'+relative,
      {method: request.method, headers, body: body as BodyInit | undefined, cache: 'no-store', signal: AbortSignal.timeout(150000)});
    return new Response(response.body, {status: response.status, headers: {
      'Content-Type': response.headers.get('content-type') || 'application/json',
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
  } catch {
    return Response.json({detail: '백엔드 연결을 확인해 주세요.'}, {status: 502});
  }
}
export const GET = proxy;
export const POST = proxy;
