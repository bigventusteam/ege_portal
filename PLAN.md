# EGE Lisans Portalı — Plan

> Durum: taslak (2026-09-25). Kararlar: ödeme = **bvpay**, süre = **sipariş bazlı**,
> aktivasyon = **çevrimiçi + çevrimdışı**, konum = **ayrı repo (`ege_portal`)**.

## 1. Hedef

mapEGE, sisEGE ve colEGE **abonelik lisansıyla** tek tek ya da paket olarak satılır.
Kullanıcı portalda:

1. Hesap açar, ürün/kademe/süre seçer (ör. *mapEGE Pro + sisEGE Standard + colEGE, 12 ay*).
2. Ödemeyi yapar; portal ödemeyi **bvpay API'si üzerinden doğrular**.
3. Abonelik başlar veya uzar, imzalı lisans üretilir.
4. Kurulum paketini indirir, lisansı **çevrimiçi** (lisans anahtarıyla) ya da
   **çevrimdışı** (parmak izi dosyası → `license.json`) aktive eder.

## 2. Bileşenler

```
┌──────────────┐  ödeme başlat / GET doğrula   ┌────────┐
│  ege_portal  │ ─────────────────────────────▶ │ bvpay  │──▶ Nestpay
│  (FastAPI +  │ ◀──── payment.result webhook ─ └────────┘
│   React)     │
│  - hesap     │   POST /api/v1/activations (lisans anahtarı + parmak izi)
│  - sipariş   │ ◀──────────────────────────────────────┐
│  - abonelik  │ ──── imzalı license.json ─────────────▶│
│  - imzalama  │                                         │
│  - indirme   │                     ┌───────────────────┴──────────┐
└──────────────┘                     │ mapEGE  │  sisEGE  │ colEGE  │
                                     │      ege_lisans (ortak)      │
                                     └──────────────────────────────┘
```

| Bileşen | İş |
|---|---|
| `ege_portal` (yeni repo) | Hesap, katalog/fiyat, sipariş, abonelik, lisans imzalama, aktivasyon API'si, indirme merkezi, yönetici paneli (`vendor/app.py`'nin yerini alır) |
| `ege_lisans` (ortak kütüphane) | Lisans şeması v2, imza doğrulama, parmak izi, saat geri alma tespiti, çevrimiçi yenileme istemcisi. Portal ve iki ürün aynı kanonik biçimi kullanır; ürünlere vendorlanır |
| mapEGE | Mevcut `services/licensing.py`, `ege_lisans`'a taşınır; şema v1 lisanslar geçerli kalır |
| sisEGE | Lisans modülü **sıfırdan** eklenir: kademe kısıtları + `/lisans` ekranı |
| colEGE | Lisans modülü **sıfırdan** eklenir (Jinja arayüzüne `/lisans` sayfası); ürünleştirme eksikleri için bkz. §9 |
| bvpay | Değişiklik istekleri (bkz. §6) |

Yığın diğer projelerle aynı: FastAPI + SQLAlchemy 2 + Alembic, üretimde
PostgreSQL (geliştirmede SQLite), React 19 + Vite + Tailwind.

## 3. Lisans şeması v2

```json
{
  "payload": {
    "schema": 2,
    "license_id": "lic_…",
    "subscription_id": "sub_…",
    "customer": {"id": "cus_…", "name": "…", "email": "…"},
    "products": {
      "mapege": {"tier": "full", "fingerprint": {"components": {"instance_id": "…", "machine_id": "…"}}},
      "sisege": {"tier": "full", "fingerprint": {"components": {"instance_id": "…", "machine_id": "…"}}},
      "colege": {"tier": "full", "fingerprint": {"components": {"instance_id": "…", "machine_id": "…"}}}
    },
    "issued": "2026-10-01",
    "expires": "2027-10-01",
    "grace_days": 14,
    "activation": {"id": "act_…", "mode": "online"}
  },
  "signature": "<ed25519 hex>"
}
```

- **Parmak izi ürün başınadır.** Hash ürün adıyla ayrıştırılır
  (`mapege|…`, `sisege|…`) ve her kurulumun kendi `instance_id`'si vardır;
  bu yüzden paket lisansında her ürün girdisi kendi parmak izini taşır.
  Tek ürünlü lisansta üst düzey `fingerprint` de kullanılabilir.
  Çevrimdışı aktivasyonda müşteri her ürünün parmak izi dosyasını yükler,
  portal hepsinde geçerli tek bir `license.json` üretir.
- v2 abonelik lisansıdır: `expires` zorunludur (süresiz lisans yalnız v1).
- Tek lisans birden çok ürün taşır. Her ürün yalnız kendi anahtarına bakar;
  `products`'ta kendi adı yoksa lisans o ürün için "missing" sayılır.
- `grace_days`: süre bitince kısa bir ek süre boyunca uyarı gösterilir,
  sonra lite/kilitli moda düşülür (ürün kapanmaz, veri kaybolmaz).
- **Çevrimiçi** aktivasyonda `expires` = min(abonelik bitişi, bugün + 30 gün).
  Ürün her gün yenilemeye çalışır; iade veya ters ibraz durumunda en geç
  30 günde düşer. **Çevrimdışı** aktivasyonda `expires` = abonelik bitişi.
- mapEGE şema 1 (`mode` alanı) lisansları okumaya devam eder.

## 4. Veri modeli (portal)

`Customer` (kurum; vergi no/daire, fatura adresi) · `User` (kuruma bağlı, rol) ·
`Product` (mapege, sisege, colege) · `Plan` (ürün/paket + kademe) ·
`Price` (plan × süre (ay) → tutar, KDV oranı, geçerlilik tarihi) ·
`Order` (kalemler, toplam, durum: `pending → paid | failed | cancelled`) ·
`Payment` (bvpay payment_id **UNIQUE**, tutar, durum, ham sonuç) ·
`Subscription` (müşteri, ürün+kademe seti, `current_period_end`, koltuk sayısı) ·
`LicenseKey` (insan-okur anahtar, **hash olarak saklanır**) ·
`Activation` (parmak izi, ürün, sürüm, son görülme, çevrimiçi/çevrimdışı, iptal) ·
`IssuedLicense` (imzalı belge kaydı) · `Release` (ürün, sürüm, platform, dosya, SHA-256, manifest) ·
`AuditEvent`.

## 5. Akışlar

### 5.1 Satın alma ve ödeme doğrulama
1. Kullanıcı sepeti onaylar → portal güncel `Price`'tan tutarı hesaplar ve
   `Order(pending)` oluşturur. Tutarı istemci belirleyemez.
2. Portal bvpay'de ödeme açar: `amount = order.total`,
   `passthrough = {order_id}`, `return_url = /odeme/sonuc`.
3. bvpay `payment.result` webhook'u gelir. **Gövdeye güvenilmez**, yalnız
   tetikleyici olarak kullanılır. Portal `GET /api/v1/payments/{id}` ile
   bvpay'den ödemeyi tekrar okur ve şunları doğrular:
   - `status ∈ {approved, captured}`
   - `amount == order.total` ve `currency == 949`
   - `passthrough.order_id == order.id`
   - `payment_id` daha önce işlenmemiş olmalı (idempotency)
4. Doğrulama başarılıysa tek bir transaction içinde:
   - `Order → paid`
   - Abonelik uzatılır: `period_end = max(bugün, mevcut_bitiş) + sipariş_süresi`
   - Lisans anahtarı yoksa üretilir, e-posta gönderilir.
5. Webhook hiç gelmezse `return_url` ve 5 dakikada bir çalışan mutabakat
   görevi aynı doğrulamayı yapar.

### 5.2 Çevrimiçi aktivasyon
Ürünün `/lisans` ekranında lisans anahtarı girilir →
`POST /api/v1/activations {license_key, product, version, fingerprint}` →
portal şunları kontrol eder: abonelik aktif mi, ürün abonelikte var mı,
koltuk limiti aşılmış mı. Uygunsa imzalı lisans döner. Ürün her gün
`POST /api/v1/activations/{id}/refresh` çağırır. Kullanıcı makine
değiştirirken portaldan eski aktivasyonu kapatır.

### 5.3 Çevrimdışı aktivasyon
Ürün parmak izi dosyasını verir (mevcut `GET /api/license/fingerprint`) →
kullanıcı dosyayı portala yükler → portal `license.json` üretir → kullanıcı
dosyayı ürüne yükler (mevcut `POST /api/license`). Yenileme de aynı yolla,
elle yapılır.

### 5.4 İndirme
Sürümler portala yüklenir (`paketle-*.ps1` çıktıları ve imzalı
`release_manifest`). İndirme için giriş yapılmış olmak yeterli (abonelik
gerekmez, bkz. aşağıdaki karar). Dosya kısa ömürlü imzalı URL ile verilir;
indirme sayfasında SHA-256 gösterilir.

**Karar (2026-10-06, EGE lider):** Oturum açmış her kayıtlı müşteri tüm
aktif İMZALI sürümleri indirebilir; abonelik ya da portal denemesi şartı
kaldırıldı. Gerekçe: kullanıcı kararı "lisanssız kurulum 7 gün çalışsın" —
ürünün kendi denemesi ve kilidi asıl kapı. Eski kural ("aktif abonelik VEYA
aktif portal denemesi") tavuk-yumurta yaratıyordu: portal deneme
aktivasyonu kurulmuş üründen gelen bir activation_request ister, ürünü
indiremeyen yeni müşteri onu üretemezdi. Takip korunur: kayıt zorunlu, her
indirme `AuditEvent("release.downloaded")` (müşteri + sürüm).
`entitled_product_ids` raporlama/ileride kademe kısıtı için kodda kalır.
İmzasız sürüm yalnız personele.

**Durum (2026-10-05):** Temel uçlar bitti — `GET /api/v1/downloads`,
`GET /api/v1/downloads/{release_id}` (2026-10-06'dan beri: oturum açmış her
müşteri, aktif imzalı sürümler; imzasız sürüm yalnız personel). Personel:
`scripts/surum_yayinla.py --personel` (created_by + `release.published`
audit) ve `POST /api/v1/admin/releases/{id}/deactivate` (gerekçeli,
`release.deactivated` audit). SHA-256 `X-Checksum-SHA256`
başlığında (ayrı bir "indirme sayfası" henüz yok, backend-yalnız bu fazda).
Henüz YOK: kısa ömürlü imzalı URL (indirme doğrudan oturum arkasında,
kalıcı bir yoldan akıyor) ve `paketle-*.ps1` çıktılarının/`release_manifest`
imzasının portala OTOMATİK yüklenmesi — bu turda yükleme yalnız
`scripts/surum_yayinla.py` CLI'sıyla, elle.

## 6. Güvenlik

- **Canlıya hazırlık sertleştirmesi (2026-10-05):** brute-force hız
  sınırlaması (e-posta+IP, `app/services/auth_throttle.py`), CSRF
  (`SameSite=Strict` + `app/middleware.py` Origin doğrulaması), parola
  politikası (≥12 karakter, ≤72 bayt — bcrypt sınırı), production'da
  fail-closed başlangıç kontrolleri (`app/startup_checks.py`), güvenlik
  başlıkları (`deploy/Caddyfile`). Ayrıntı ve gerekçe için bkz.
  README.md "Tasarım kararları" aynı başlık ve "Canlıya alma" bölümü.
- **İmza anahtarı EGE ailesinde ortaktır:** portal paket lisansını tek anahtarla
  imzaladığı için mapEGE, sisEGE ve colEGE aynı açık anahtar listesini gömer
  (ürün başına ayrı anahtar paket satışını bozar). Geliştirmede ortak EGE
  geliştirme çifti `ege_platform/_anahtarlar/gelistirme/` altındadır.
- **İmza anahtarı (üretim):** Yeni **üretim** Ed25519 çifti oluşturulur: birincil + kasada
  bekleyen yedek. Geliştirme anahtarları kaldırılır. Özel anahtar veritabanında
  değil, secret olarak bağlanan dosyada durur. İmzalama portalda ayrı bir
  modüldür; sonra ayrı imzalama servisine ya da KMS/HSM'e taşınabilir.
- **Lisans zorunluluğu:** Satılan paketlerde `MAPEGE_REQUIRE_LICENSE=1`
  (şu an 0; müşteri `MAPEGE_MODE=pro` yazarak lisanssız pro kullanabiliyor).
  sisEGE'de de aynı kural uygulanır.
- **bvpay bağımsız bir projedir (karar 2026-09-26):** Portal kart bilgisi
  almaz; yalnız ödeme talebini (sipariş, tutar, müşteri, dönüş adresi)
  bvpay'e gönderir. Tahsilatı ve **kampanya altyapısını** bvpay yürütür.
  Entegrasyon ayrıntıları sonra ele alınacak. O zaman netleşecekler:
  - **Kampanya ve tutar doğrulaması:** Portal şu an bvpay'in bildirdiği
    tutarın sipariş tutarına birebir eşit olmasını istiyor. bvpay kampanya
    indirimi uygularsa bu kontrol ödemeyi reddeder. Çözüm seçenekleri:
    bvpay sonuçta liste fiyatı, uygulanan kampanya ve indirimi bildirir,
    portal bunları doğrular; ya da portal sipariş anında tutarı bvpay'den
    teklif olarak alır ve siparişe yazar.
  - Webhook'a HMAC imzası (`X-BVPay-Signature`). Portal zaten GET ile
    doğruluyor, imza ek bir katman olur.
  - Checkout ucu ve mutabakat görevi bu entegrasyonla birlikte yazılır.
- **Portal:** Lisans anahtarları hash'lenerek saklanır. Aktivasyon uçlarında
  rate limit olur. Admin işlemleri audit log'a yazılır. Parolalar bcrypt ile
  saklanır ve e-posta doğrulaması yapılır.
- **Lisans zorunluluğu hiçbir env değişkeniyle kapatılamaz** (ne
  `MAPEGE_REQUIRE_LICENSE` ne `ENVIRONMENT=development`). Geliştirme
  ortamı, geliştirme anahtarıyla imzalı bir lisansla çalışır; satılan
  paketlere yalnız üretim açık anahtarları gömülür.
- **Aktivasyon isteğine güvenilmez.** Müşterinin yüklediği
  `activation_request` dosyasında `instance_id` zorunludur, yalnız bilinen
  bileşen adları ve sha256 değerleri kabul edilir, okunamayan kimliğin
  sabit değeri (`"unknown"`) reddedilir. `ege_lisans` de v2'de çapasız
  eşleşmeye izin vermez.
- **Bilinen sınır (çevrimdışı lisans):** `machine_id` her ortamda
  bulunamadığı için (ör. Docker) zorunlu değildir. Veri dizinini
  (`instance_id` dosyasını) kopyalayıp aktivasyon dosyasından `machine_id`'yi
  silen kararlı bir müşteri, çevrimdışı lisansı çoğaltabilir. Bu, imzalı dosya
  tabanlı lisanslamanın yapısal sınırıdır. Önlemler: (1) aynı `instance_id`
  farklı müşterilerde görülürse denetim kaydı, (2) asıl kontrol çevrimiçi
  aktivasyondaki koltuk sayımı ve günlük yenileme, (3) sözleşmedeki lisans
  koşulları.

## 7. Fazlar

| Faz | İçerik | Bağımlılık |
|---|---|---|
| **F0 Hazırlık** | colEGE ürünleştirme temeli (§9); mapEGE hijyeni (`users.json`, `vendor/lisans_kayitlari.db`, `data/` git'ten çıkar); üretim anahtar çiftleri; satılan profillerde `REQUIRE_LICENSE=1`; sisEGE ve colEGE kademelerini tanımla | — |
| **F1 Ortak lisans** | `ege_lisans` kütüphanesi + şema v2 + contract testleri; mapEGE geçişi (v1 uyumlu); sisEGE ve colEGE lisans modülleri + kademe kısıtları | F0 |
| **F2 Portal çekirdeği** | Hesap/kurum, katalog/fiyat, sipariş, abonelik, imzalama, **çevrimdışı aktivasyon**, yönetici paneli (elle sipariş onayı: havale/EFT, kamu kurumları — bitti 2026-10-05, bkz. §8 madde 5) | F1 |
| **F3 Ödeme** | bvpay entegrasyonu, webhook + GET doğrulama, mutabakat görevi, iade/iptal → abonelik geri alma | F2, bvpay |
| **F4 Çevrimiçi aktivasyon** | Aktivasyon API'si, ürün tarafında anahtar girişi + günlük yenileme, koltuk/makine yönetimi | F2 |
| **F5 İndirme merkezi** | Sürüm yükleme, imzalı manifest, yetkili indirme — temel uçlar + personel yayınla/yayından kaldır bitti (2026-10-06, bkz. §5.4); indirme hakkı = oturum açmış her müşteri; kısa ömürlü imzalı URL, indirme sayfası (frontend) ve paketleme çıktılarının otomatik yüklenmesi açık | F2 |
| **F5b Dağıtım tek kaynağı** | Test ve üretim sunucusu kaynağı depodaki `paket_tanimi.json` + `scripts/paket_secimi.py` ile seçsin (bugün sunucuda ayrı, kapalı bir allowlist var; yeni modüller sessizce düşüyor). Şartlar: tanım ve kod aynı commit'te değişir, CI her commit'te `paket_secimi.py` koşar, sunucu "bu tanım bu commit'te uygulanamıyor" diye reddedebilir. Geliştirme araçları (`gelistirme_lisansi_uret.py`, senkron betikleri) paketlere girmez. sisEGE ve colEGE'de henüz `paket_tanimi.json` yok (yalnız mapEGE'de var). Konteyner dağıtım şartları (2026-09-27 sunucu testinden): her üründe lisans/deneme dizini kalıcı ve servisler arası paylaşımlı volume'de (aksi hâlde recreate denemeyi sıfırlar); sabit `hostname:` ve host `/etc/machine-id` salt-okunur bağlaması (aksi hâlde recreate sonrası parmak izi eşleşmez); `network_mode: service:mapege` kullanan servisler mapege recreate edilince yeniden oluşturulmalı ve healthcheck taşımalı | F5 |
| **F6 Üretime hazırlık** | Bitiş hatırlatma e-postaları, e-fatura/e-arşiv, mesafeli satış sözleşmesi + KVKK metinleri, Authenticode kod imzalama, portal barındırma/domain; **yayın sırası:** portalın tier="full" üreten sürümü ancak mapEGE'nin v2 lisansta tier'dan bağımsız tam sürüm kabulü sahaya çıktıktan sonra yayınlanır (bkz. §8 madde 2) | F3–F5 |

F3 bvpay'in banka bilgilerini beklerken mock modda geliştirilebilir.

## 8. Açık sorular

1. **Fiyat ve süreler:** Hangi süreler satılacak (1 / 12 ay?), paket indirimi olacak mı?
   **Karar (2026-09-28):** KDV hariç fiyat + kırılım; oran Price'tan.
   `Price.amount` KDV HARİÇ net tutardır, `Order` bunu `net`/`vat_rate`/
   `vat_amount`/`total` (KDV dahil) olarak snapshot'lar.
   **Karar (2026-10-05):** 1 aylık ve 12 aylık paketler AYRI fiyatlanır
   (her plan için iki `Price` satırı, months=1 ve months=12). 7 günlük
   deneme ayrıca verilir (ücretsiz, §8 madde 7). Tutarlar henüz belirlenmedi.
2. ~~**sisEGE ve colEGE kademeleri**~~ — **KAPANDI. Karar (2026-10-06,
   kullanıcı): Kademe yok — lisans tam sürüm; `tier` alanı şema uyumluluğu
   için `"full"`.** Üç üründe de (mapEGE dahil) satın alınan lisans ürünün
   tamamını açar. İmzalı şema v2 `products.<kod>.tier` alanını zorunlu
   tuttuğu için alan kalır, değeri her zaman `"full"` (`app/models.py::
   TAM_SURUM_TIER`): `PlanItem.tier` varsayılanı `"full"`, mevcut satırlar
   migration `5d2a7c4e1f93` ile `"full"`a çevrildi (yalnız UPDATE); çevrimdışı
   aktivasyon ve deneme lisansı DB'deki değere bakmadan `"full"` yazar; API
   yanıtları ve arayüz tier göstermez ("Tam sürüm"). Katalog: ürün başına tek
   plan (+ paket planları), plan/fiyat kodunda tier'a göre dallanma yok.
   **Yayın sırası bağımlılığı:** mapEGE şema v2 lisansta tanımadığı tier'ı
   fail-closed `lite` sayıyordu (`services/licensing.py::
   _effective_mode_from_license`). Portalın `"full"` üreten sürümü, mapEGE'nin
   "geçerli v2 lisansta tier'a bakma → pro" değişikliği main'e girip sahaya
   çıkmadan YAYINLANMAZ — aksi hâlde ödeme yapan her mapEGE müşterisi lite
   modda kalır. `MAPEGE_MODE` dağıtım tavanı ve v1 lisansların `mode`'u
   aynen geçerli. Önceki karar (2026-10-05, aşağıda) bununla AŞILDI:
   **Karar (2026-10-05):** sisEGE ve
   colEGE'de kademe YOK: ürünü satın alan tüm özellikleri kullanır (lisansta
   tek kademe, ürünler kademeye göre özellik kapatmaz). mapEGE'nin
   lite/standard/pro kademeleri aynen kalır. Eski soru: mapEGE'deki lite/standard/pro'nun bu iki üründeki
   karşılığı ne? Hangi özellik hangi kademede? (colEGE için aday ayrım: MGM +
   radar temel, harici servis çerçevesi + AI asistan üst kademe.)
3. ~~**Lisans birimi**~~ — **Karar (2026-10-05):** MAKİNE başına. Bir abonelik
   adedi bir makineye (kurulum parmak izine) bağlanır; birden çok makine =
   sipariş adedi (her adet bir aktivasyon hakkı). Makine değişikliği personel
   onaylı taşıma ile (eski aktivasyon iptal, audit). Eski soru: Kurulum (makine) başına mı, kurum başına mı? Koltuk
   sayısı ve pro'da `SERVICE_ROLE` ile çok sunuculu kurulum nasıl sayılacak?
   **Ek karar (2026-10-06):** `seats` sınırı abonelik başına DEĞİL, PER-ÜRÜN
   sayılır — bir paket satışında ürünler farklı makinelerde olabileceğinden
   (bkz. app/services/offline_activation.py docstring'i), toplam sayım
   2+ ürünlü bir pakette seats=1'i hiçbir zaman aktive edilemez hâle getirirdi.
4. **Deneme sürümü:** 14/30 günlük ücretsiz deneme lisansı olacak mı?
5. **Kurumsal ödeme:** Kamu kurumu ve belediye müşterileri genelde kartla
   ödemez. Havale/EFT veya teklif → yönetici onayı akışı gerekli mi?
   **Karar (2026-10-05):** Evet — bvpay banka bilgilerini beklerken personel
   (`is_staff`) `POST /api/v1/admin/orders/{id}/mark-paid` ile havale/EFT
   ödemesini ELLE "ödendi" işaretler (bkz. app/services/manual_payments.py).
   Görevler ayrılığı: personel kendi müşterisine ait bir siparişi
   işaretleyemez. Tutar sipariş toplamına (KDV dahil) tam eşit olmalı —
   kısmi ödeme yok. Banka referansı (dekont/işlem no) sistem genelinde
   tekil. Onaylandıktan sonraki etkiler (abonelik uzatma + lisans üretme)
   bvpay akışıyla AYNI `apply_payment_effects` fonksiyonundan geçer.
6. **Fatura:** e-Arşiv/e-Fatura entegratörü (Paraşüt, Logo, vb.) kullanılacak mı?
   **Karar (2026-10-05):** e-Fatura entegrasyonu OLACAK; entegratör hizmeti
   henüz satın alınmadı. Portal fatura verisini (unvan, VKN/TCKN, vergi
   dairesi, adres, sipariş kırılımı) şimdiden toplar ve entegratörden bağımsız
   bir "kesilecek fatura" kuyruğu tutar; entegratör seçilince yalnız gönderici
   adaptörü yazılır.
7. ~~**Lisanssız kurulum / deneme**~~ — **Karar (2026-09-26):** Lisanssız
   kurulum ilk çalıştırmadan itibaren **7 gün** çalışır, sonra kilitlenir ve
   kullanıcı lisans alması için bilgilendirilir (yalnız lisans ekranı ve
   portal bağlantısı açık kalır). Süreyi **üretici** değiştirir, müşteri
   değiştiremez:
   - Ürüne gömülü varsayılan: 7 gün (sabit, env ile değiştirilemez).
   - Genel ve müşteri bazında süre (kampanyalar): portal yönetici ayarı. Portal
     bu süreyle **imzalı deneme lisansı** (`license_type: "trial"`) üretir;
     ürün bunu normal v2 lisans gibi doğrular.
   - Aynı kurulum (instance_id) ve aynı müşteri için deneme lisansı tekrar
     tekrar alınamaz; ek süreyi yalnız üretici verebilir.
   - Bilinen sınır: gömülü 7 günlük süre veri dizininde tutulur. Veri dizinini
     silen kullanıcı süreyi sıfırlayabilir, ama bu kendi verisini de siler.
   - **Abonelik süresi dolan ücretli müşteri (karar 2026-09-26):** `grace_days`
     boyunca ürün çalışmaya ve colEGE'de veri toplama devam eder (uyarı
     gösterilir); ek süre bitince toplama durur ve kilit devreye girer.
     Gerekçe: colEGE'de kaçırılan veri geri getirilemez. sisEGE'de zamanlanmış
     görev kapısı da aynı kuralı izler (grace = lisanslı sayılır).
8. ~~**MGM verisi**~~ — **Karar (2026-09-25):** MGM ve radar verisi ürünle gelmez.
   Kurulumda servis oluşturulmaz; isteyen müşteri kendi API bilgileriyle panelden
   şablondan ekler. colEGE'de uygulandı (bkz. §9). Radar bir API değil,
   mgm.gov.tr'deki herkese açık görüntüler; kimlik istenmez.
9. ~~**Kart bilgisi nerede alınır**~~ — **Karar (2026-09-26):** Portal kart
   almaz. bvpay bağımsız proje; ödeme talebini alır, kampanyalara göre
   tahsil eder. Entegrasyon sonra ele alınacak (bkz. §6).
10. ~~**Portal adresi**~~ — **Karar (2026-10-05):** `https://portal.bigventus.com`.
   Ürünlerdeki `PORTAL_URL` varsayılanları bu adres; portal dağıtımında
   `PORTAL_DOMAIN`/`ALLOWED_ORIGINS` örnekleri de buna göre.

## 9. colEGE — satılabilir ürün için eksikler

colEGE (github.com/bigventusteam/colEGE, dal `master`), MGM ücretli API'sinden
hava durumu, tahmin, meteoalarm ve yıldırım verisini PostGIS'e arşivliyor.
Radar PNG'lerini renk analiziyle yağış seviye matrisine çeviriyor ve genel
amaçlı zamanlanmış "harici servis" çekme çerçevesi sunuyor. Başlangıçtaki
kullanım amacı şarj istasyonları için hava ve yıldırım erken uyarısı.
Kod küçük ve temiz: ~4.700 satır, 38 uç, 75 test, sürümleri sabit
bağımlılıklar, Alembic tek kaynak, `.env` git'te değil. Ürün olarak satmak
için şunlar eksik:

| Konu | Durum | Gereken |
|---|---|---|
| Lisans | Yok | `ege_lisans` + kademe kısıtları |
| Kullanıcılar | `.env`'de tek admin, oturum 7 gün, çerezde `secure` yok | Çok kullanıcı + rol; mapEGE/sisEGE ile ortak kimlik hedefi (EGE Core/OIDC) |
| Paketleme | **Kısmen yapıldı:** Dockerfile (non-root, tek worker) + compose (PostGIS, başlangıçta `alembic upgrade head`, sırlar `.env`'den zorunlu) | Windows kurulum paketi, imzalı release manifest (mapEGE'deki araçlar yeniden kullanılır) |
| Zamanlayıcı | Süreç içi thread; birden fazla uvicorn worker'ında işler kopyalanır | Tek worker kuralı ya da DB kilidi / ayrı zamanlayıcı süreci |
| ~~FastAPI~~ | **Yapıldı:** `lifespan`'a geçildi | — |
| AI asistan | Gemini'ye API yanıtları gönderiliyor | Varsayılan kapalı, müşteri kendi anahtarını girer; KVKK açısından kullanıcıya bildirim |
| Veri paylaşımı | Veriyi yalnız kendi arayüzünde ve `/api/servisler/{id}/veri` üzerinden sunuyor | sisEGE `generic_rest` / `ogc_api_features` connector'ı ile tüketilebilir bir okuma API'si (API anahtarlı); böylece mapEGE ve sisEGE üzerinden haritada gösterim |
| Depo | `WEB SERVİS.docx` git'te (yalnız `xxx` yer tutucuları var, sır yok) | `docs/` altına taşı |
| ~~MGM/radar varsayılan~~ | **Yapıldı:** kurulumda servis yok; "Şablondan" ile müşteri kendi API adresi/kullanıcı/parolasıyla ekler; kimlik `.env` yerine servis kaydında | Parolalar DB'de düz metin — sisEGE'deki `crypto_envelope` benzeri şifreleme |
