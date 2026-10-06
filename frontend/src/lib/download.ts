/** Bir `Blob`'u tarayıcıda "farklı kaydet" gibi indirtir — hem dosya
 * indirme (İndirmeler sayfası) hem de JSON `license.json` indirme
 * (çevrimdışı aktivasyon / deneme / yeniden indir) AYNI mekanizmayı
 * kullanır (ikincisi önce `jsonBlobOlustur` ile bir Blob'a çevrilir). */
export function blobIndir(blob: Blob, dosyaAdi: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = dosyaAdi
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function jsonBlobOlustur(data: unknown): Blob {
  return new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
}

export const MAX_ACTIVATION_REQUEST_BAYT = 16 * 1024 // app/services/activation_request.py::MAX_ACTIVATION_REQUEST_BYTES ile AYNI

export function boyutGosterimi(bayt: number): string {
  if (bayt < 1024) return `${bayt} B`
  if (bayt < 1024 * 1024) return `${(bayt / 1024).toFixed(1)} KB`
  if (bayt < 1024 * 1024 * 1024) return `${(bayt / (1024 * 1024)).toFixed(1)} MB`
  return `${(bayt / (1024 * 1024 * 1024)).toFixed(2)} GB`
}
