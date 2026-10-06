/**
 * Backend `currency` alanlarını ISO 4217 SAYISAL kodla taşıyor (ör. "949" —
 * TRY'nin numerik kodu, bkz. app/models.py::Price.currency). Bu, ham hâliyle
 * müşteriye gösterilirse ("12000.00 949") hiçbir anlam taşımaz — formatlama
 * HER ZAMAN bu modülden geçmeli, hiçbir sayfa ham `currency`/tutar alanını
 * doğrudan JSX'e YAZMAMALI (2026-10-05, EGE lider'in gerçek tarayıcı
 * incelemesinde bulundu).
 *
 * Sembol kasıtlı olarak Intl'in KENDİ para birimi biçimlendirmesiyle DEĞİL,
 * elle sayı + sembol birleştirerek üretiliyor: `Intl.NumberFormat(...,
 * {style:'currency'})`'in sembolü sayının ÖNÜNE mi SONRASINA mı koyacağı
 * çalışma zamanının ICU/CLDR sürümüne göre değişebiliyor (bu makinede Node
 * sembolü ÖNE koyuyor: "₺12.000,00"; tarayıcılarda tersi görülebiliyor) —
 * istenen biçim ("12.000,00 ₺") deterministik olsun diye sayı ayrı
 * formatlanıp sembol elle SONRASINA ekleniyor.
 */
const PARA_BIRIMI_SEMBOLU: Record<string, string> = {
  '949': '₺', // TRY
}

function sayiMetni(sayi: number, basamak = 2): string {
  return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: basamak, maximumFractionDigits: basamak }).format(
    sayi,
  )
}

/** `deger` backend'den gelen `Decimal` string'i (ör. "12000.00"),
 * `numerikKod` ISO 4217 sayısal kod (ör. "949"). Bilinmeyen bir kod ya da
 * ayrıştırılamayan bir tutar gelirse ÇÖKMEDEN ham kodu gösterir. */
export function tutarGoster(deger: string, numerikKod: string): string {
  const sayi = Number(deger)
  if (Number.isNaN(sayi)) return `${deger} ${numerikKod}`

  const sembol = PARA_BIRIMI_SEMBOLU[numerikKod]
  return sembol ? `${sayiMetni(sayi)} ${sembol}` : `${sayiMetni(sayi)} ${numerikKod}`
}

/** KDV oranı gösterimi — gereksiz ondalık YOK: "20.00" → "20", "7.50" → "7,5". */
export function oranGoster(deger: string): string {
  const sayi = Number(deger)
  if (Number.isNaN(sayi)) return deger
  return new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(sayi)
}
