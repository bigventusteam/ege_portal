/**
 * API istemcisi. Oturum HttpOnly bir çerezle taşınır (bkz.
 * app/routers/auth.py::get_current_user) — burada hiçbir token
 * localStorage'a/JS'e YAZILMAZ, `credentials: 'include'` ile tarayıcı
 * çerezi otomatik gönderir. Geliştirmede `vite.config.ts`'deki proxy
 * `/api/*`'i backend'e (8002) yönlendirdiği için istek AYNI ORİJİNDEN
 * gidiyormuş gibi görünür — CORS/credentials karmaşası yok.
 */

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Backend'in HTTPException gövdesi `{"detail": "..."}` ya da (pydantic
 * doğrulama hatalarında) `{"detail": [{"msg": "...", ...}, ...]}` olabilir —
 * ikisini de kullanıcıya gösterilebilir tek bir metne indirger. Bu projede
 * `HTTPException` mesajları HER ZAMAN kullanıcıya gösterilmek üzere
 * yazılmıştır (bkz. ege_portal/README.md), iç ayrıntı/yığın izi sızdırmaz —
 * bu yüzden `detail` doğrudan gösterilebilir; yalnız BEKLENMEYEN (ağ hatası,
 * JSON-olmayan 5xx gövdesi vb.) durumlarda sabit bir mesaja düşülür. */
function hataMesajiCikar(detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parcalar = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => !!m)
    if (parcalar.length) return parcalar.join(', ')
  }
  return 'Beklenmeyen bir hata oluştu.'
}

export function hataGoster(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Beklenmeyen bir hata oluştu.'
}

type OturumDustuCallback = () => void
let oturumDustuCallback: OturumDustuCallback | null = null

/** `main.tsx` bunu BİR KEZ bağlar (auth store'u temizler + /giris'e yönlendirir).
 * Burada doğrudan router/store'a bağımlı olmamak için bilerek bir
 * indirection — api client'ın kendisi React/zustand'dan HABERSİZ kalır. */
export function onSessionExpired(cb: OturumDustuCallback): void {
  oturumDustuCallback = cb
}

const OTURUM_ACMA_YOLLARI = ['/api/v1/auth/login', '/api/v1/auth/register']

async function hataFirlat(resp: Response): Promise<never> {
  let detail: unknown = null
  try {
    const gövde = await resp.json()
    detail = gövde?.detail
  } catch {
    // Gövde yok ya da JSON değil — detail null kalır, hataMesajiCikar genel mesaja düşer.
  }
  throw new ApiError(resp.status, hataMesajiCikar(detail))
}

async function istek<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, { ...init, credentials: 'include' })

  // 401: oturum geçersiz/süresi dolmuş — ama giriş/kayıt denemesinin KENDİSİ
  // 401 dönerse (yanlış şifre) bu bir oturum düşmesi DEĞİL, normal bir form
  // hatasıdır; çağıran kendi try/catch'inde ele alır, burada yönlendirme
  // TETİKLENMEZ.
  if (resp.status === 401 && !OTURUM_ACMA_YOLLARI.some((y) => path.startsWith(y))) {
    oturumDustuCallback?.()
  }

  if (!resp.ok) await hataFirlat(resp)

  if (resp.status === 204) return undefined as T
  const contentType = resp.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) return (await resp.json()) as T
  return undefined as T
}

export interface DosyaYaniti {
  blob: Blob
  dosyaAdi: string | null
}

function contentDispositionDosyaAdi(resp: Response): string | null {
  const cd = resp.headers.get('content-disposition') ?? ''
  const eslesme = /filename="?([^";]+)"?/i.exec(cd)
  return eslesme ? eslesme[1] : null
}

export const api = {
  get: <T>(path: string): Promise<T> => istek<T>(path),

  post: <T>(path: string, body?: unknown): Promise<T> =>
    istek<T>(path, {
      method: 'POST',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  // `FormData` ile çağrılır (dosya yükleme) — Content-Type BİLEREK elle
  // set EDİLMEZ, tarayıcı multipart sınırını (boundary) kendisi ekler.
  postForm: <T>(path: string, form: FormData): Promise<T> => istek<T>(path, { method: 'POST', body: form }),

  async getBlob(path: string): Promise<DosyaYaniti> {
    const resp = await fetch(path, { credentials: 'include' })
    if (resp.status === 401 && !OTURUM_ACMA_YOLLARI.some((y) => path.startsWith(y))) {
      oturumDustuCallback?.()
    }
    if (!resp.ok) await hataFirlat(resp)
    return { blob: await resp.blob(), dosyaAdi: contentDispositionDosyaAdi(resp) }
  },
}
