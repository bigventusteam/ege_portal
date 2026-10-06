# EGE Lisans Portalı — backend çekirdeği

mapEGE, sisEGE ve colEGE'nin abonelik lisansını satan portalın FastAPI arka
ucu. Kararlar ve veri modelinin gerekçesi `PLAN.md`'dedir; bu README yalnız
kurulum ve bu fazda yapılan tasarım seçimlerini anlatır.

Bu faz **yalnız backend çekirdeği**: sipariş, fiyat hesabı, bvpay ödeme
doğrulama, abonelik uzatma, gerçek `ege_lisans` ile imzalanan lisans
üretimi, çevrimdışı aktivasyon, deneme (trial) lisansı yönetimi, indirme
merkezi (F5 — temel uçlar, bkz. aşağı). Frontend yok. Çevrimiçi aktivasyon
(anahtar girişi + günlük yenileme, F4), ödeme başlatma ucu ve mutabakat
görevi sonraki fazlar/turlar (bkz. "Kapsam dışı bırakılanlar").

## Yığın

FastAPI + SQLAlchemy 2 + Alembic. Geliştirmede SQLite, üretimde PostgreSQL
(`DATABASE_URL` ile seçilir — kod tarafında fark yok).

## Kurulum

```
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # SECRET_KEY ve EGE_LISANS_OZEL_ANAHTAR'ı doldurun
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002
```

`DATABASE_URL` tanımlı değilse varsayılan `sqlite:///./ege_portal.db` kullanılır.

`requirements.txt`, `ege_lisans`'ı **editable yol bağımlılığı** olarak kurar
(`-e ../ege_lisans`) — vendorlama değil, portal sunucu tarafı olduğu için
buna gerek yok (bkz. Tasarım kararları). `pip install -r requirements.txt`
bu yüzden `ege_portal/` içinden çalıştırılmalı (yol ona göre çözülür);
`ege_lisans` reposu bu repoyla aynı üst dizinde (`ege_platform/ege_lisans`)
olmalı.

### Lisans imzalama anahtarı

Gerçek bir lisans imzalamak (ödeme sonrası ya da çevrimdışı aktivasyonda)
için `EGE_LISANS_OZEL_ANAHTAR` bir Ed25519 özel anahtar dosyasının YOLUNU
göstermeli. Geliştirme için yeni bir çift üretmek:

```
python -c "from ege_lisans.signing import generate_keypair; print(generate_keypair('dev_license_key.pem'))"
```

Bastırılan hex açık anahtarı saklayın (ürünlerin `PUBLIC_KEYS` listesine
gireceği değer budur); `.env`'de `EGE_LISANS_OZEL_ANAHTAR=dev_license_key.pem`
yazın. Tanımsızsa ya da dosya yoksa imzalama AÇIK bir hatayla durur —
sessizce imzasız lisans üretilmez (bkz. `app/licensing.py`).

### Personel (üretici) hesabı

Deneme süresi ayarları gibi platform-genelinde üretici uçları
(`/api/v1/admin/...`) `User.is_staff` gerektirir — bu, `POST /auth/register`
gibi self-servis hiçbir uçtan set edilemez (bkz. Tasarım kararları,
"rol karışıklığı" düzeltmesi). İlk personel hesabını oluşturmak/var olan
bir kullanıcıyı yükseltmek için:

```
python scripts/personel_olustur.py --email admin@bigventus.com
```

Parola argv'den alınmaz — bir terminalde sorulur (`getpass`), yoksa
stdin'in ilk satırından okunur. Var olan bir kullanıcıyı yükseltirken
parola hiç sorulmaz/değiştirilmez.

## Şema yönetimi

colEGE ile aynı kural: şemanın tek kaynağı `alembic/versions/`'dir,
`app/models.py` içinde `Base.metadata.create_all()` **yok**. Geliştirmede de
`alembic upgrade head` çalıştırılır. Testler kendi izole bellek-içi
SQLite'ında `create_all()` kullanır (yalnız test fixture'ı, bkz.
`tests/conftest.py`) — bu, gerçek dağıtımdaki Alembic akışını değiştirmez.

## Testler

```
pytest
```

Ağsız/DB'siz çalışır: `tests/conftest.py` her testte taze bir bellek-içi
SQLite açar, gerçek bvpay yerine `tests/fakes.py::FakeBVPayClient` kullanılır.
Gerçek ağa hiçbir test çıkmaz. `tests/test_offline_activation.py` istisna
olarak GERÇEK `ege_lisans` imzalama/doğrulamasını kullanır — ağa çıkmaz,
yalnızca testin kendi ürettiği geçici bir Ed25519 anahtar çiftini kullanır
(bkz. o dosyadaki `anahtar_cifti`/`gercek_imzalayici` fixture'ları); diğer
tüm testler `tests/fakes.py::FakeImzalayici` ile sahte imza kullanmaya
devam eder.

### Gerçek PostgreSQL'e karşı eşzamanlılık testi (opsiyonel)

`tests/test_postgres_yaris.py`, `Order` satırındaki `SELECT ... FOR UPDATE`
kilidinin PostgreSQL'de GERÇEKTEN işlediğini (SQLite'ta etkisiz olduğu
zaten dokümante edildi) gerçek thread'ler + geçici bir Postgres
konteyneriyle doğrular. `PORTAL_PG_URL` tanımlı değilse ATLANIR — normal
`pytest` çalıştırması buna dokunmaz:

```
docker run --rm -d --name portal-pg-yaris -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=portal_yaris -p 55432:5432 postgres:16
PORTAL_PG_URL="postgresql://postgres:test@localhost:55432/portal_yaris" \
    pytest tests/test_postgres_yaris.py -v
docker rm -f portal-pg-yaris
```

Her test kendi `SessionLocal` fixture'ında şemayı DROP+CREATE eder —
paylaşılan bir konteynerde ÇALIŞTIRMAYIN, yalnız bunun için ayrılmış geçici
bir Postgres kullanın. 5'er tekrarla doğrulandı (10/10); `with_for_update()`
devre dışı bırakılınca ikinci senaryo (aynı siparişe iki farklı ödeme)
5/5 düşüyor — kilidin gerçekten işlediğinin kanıtı.

## Tasarım kararları

- **Sipariş tek plan/süre taşır** (`POST /api/v1/orders {plan_id, months}`,
  PLAN.md §5.1 ile birebir) — bkz. birkaç madde aşağıdaki paket/plan kararı.
- **Fiyat sipariş anında `Order`'a SNAPSHOT'lanır** (`net`, `currency`,
  `vat_rate`, `vat_amount`, `total`). `Price` ileride değişse/silinse bile
  eski siparişin tutarı sabit kalır — hem doğru fatura hem de bvpay tutar
  doğrulamasının "hangi tutara göre" sorusu netleşiyor.
- **`Price.amount` KDV HARİÇ net tutardır** (KARAR 2026-09-28, müşteri
  testinde bulundu — bkz. PLAN.md §8 madde 1; önceki "KDV DAHİL" varsayımı
  YANLIŞ çıktı, `total` KDV'yi hiç eklemiyordu — ör. `vat_rate=20` iken
  `total=12000`, olması gereken `14400`). `Order.vat_amount`,
  `net * vat_rate / 100`'den `Decimal`/`ROUND_HALF_UP` ile 2 basamağa
  yuvarlanarak hesaplanır (`app/services/orders.py::create_order`),
  `total = net + vat_amount` KDV DAHİL nihai tutardır — bvpay'e giden ve
  karşılaştırılan tutar hâlâ `total` (davranış değişmedi, yalnız artık
  doğru hesaplanıyor). `OrderResponse` bu kırılımın tamamını döndürür.
- **Sipariş tek `plan_id` taşımaya devam ediyor** — paketler zaten `Plan`ın
  birden çok `PlanItem` (ürün) taşıyabilmesiyle çözülüyor; "mapEGE +
  sisEGE + colEGE, 12 ay" gibi bir paket bir PAKET PLANI olarak okunmalı, çok
  kalemli bir sepet değil.
- **Kademe yok — lisans tam sürüm** (kullanıcı kararı 2026-10-06, PLAN.md §8
  madde 2). `PlanItem.tier` yalnız imzalı şema v2 uyumluluğu için duruyor,
  değeri her zaman `"full"` (`app/models.py::TAM_SURUM_TIER`); lisans
  üreten kod DB değerine bakmadan `"full"` yazar, API yanıtları tier taşımaz.
  Yayın sırası: bu sürüm, mapEGE'nin v2 lisansta tier'dan bağımsız tam sürüm
  kabulü sahaya çıkmadan yayınlanmaz (mapEGE tanımadığı tier'ı `lite`
  sayıyordu).
- **Ödeme doğrulama webhook gövdesine güvenmez** (PLAN.md §5.1 madde 3).
  `POST /api/v1/webhooks/bvpay` gövdesinden yalnızca `payment_id` ve bir
  `order_id` İPUCU okur; asıl doğru `passthrough.order_id` bvpay'den taze
  `GET` ile gelen yanıttan alınır ve karşılaştırma ona göre yapılır. Yani
  webhook gövdesi sahte bir `order_id` taşısa bile yanlış siparişi
  `paid`e çeviremez (bkz. `tests/test_webhook.py::test_webhook_govdeye_guvenmez_gercek_dogrulama_get_ile`).
- **İdempotency `Payment.processed_at`'e dayanır**, `bvpay_payment_id`
  UNIQUE kısıtı ikinci bir güvenlik katmanı. Aynı `payment_id` iki kez
  işlenmeye çalışılırsa (ör. webhook + mutabakat görevi, ya da bvpay'in
  kendi tekrar denemesi) ikinci çağrı var olan `Payment`'ı olduğu gibi
  döner, abonelik tekrar uzamaz, ikinci bir `LicenseKey` üretilmez.
  Reddedilen bir deneme (`declined` vb.) `Payment` satırı YARATMAZ — bu
  yüzden aynı `payment_id` önce reddedilip sonra onaylanırsa (bankanın 3D
  onayı gecikmesi gibi) ikinci deneme normal şekilde işlenir.
- **Aynı siparişe İKİNCİ bir ödeme reddedilir** (`OrderAlreadyPaid`,
  `app/services/payments.py`). İlk taslakta `verify_and_process` yalnız
  `payment_id` bazında idempotent'ti — sipariş durumuna hiç bakmıyordu.
  Yani müşteri aynı siparişi FARKLI iki `payment_id` ile iki kez öderse
  (çift tıklama, iki sekme) ikisi de tüm kontrollerden geçip aboneliği
  ÇİFT uzatabiliyordu (12 aylık sipariş 24 ay yapardı) — bu gerçek parayı
  etkileyen bir hataydı, EGE lider'in incelemesinde yakalandı. Artık
  `order.status != PENDING` (zaten `paid`, ya da `cancelled`/`failed`)
  iken gelen, aksi halde geçerli görünen bir ödeme aboneliği UZATMAZ;
  yine de `Payment(processed_at=None)` olarak kaydedilir ve
  `AuditEvent("payment.duplicate_for_order")` yazılır — elle iade
  edilebilsin diye (bkz. `tests/test_payments_verification.py` ve
  `tests/test_webhook.py::test_webhook_ayni_siparise_ikinci_odeme_reddedilir`).
- **Eşzamanlı doğrulama** (webhook + mutabakat görevi aynı `payment_id`'yi
  aynı anda kontrol ederse): `Order` satırı `SELECT ... FOR UPDATE` ile
  okunur (PostgreSQL'de ikinci isteği sıraya sokar; SQLite'ta etkisizdir —
  sürücü desteklemiyor). Ek güvence olarak `bvpay_payment_id` INSERT'inden
  `db.commit()`'e kadar olan TÜM blok `IntegrityError`'a karşı sarmalı
  (yalnız `commit()`'i sarmak YETERSİZ — `extend_subscription`/
  `ensure_license_key` kendi içinde `db.flush()` çağırdığı için UNIQUE
  ihlali commit'ten ÖNCE bir flush'ta da patlayabilir, bkz. koddaki not).
  Kaybeden taraf rollback edip kazananın `Payment` satırını idempotent
  döner. `tests/test_payment_concurrency.py` bunu mock'lanmış bir istisna
  ile DEĞİL, aynı dosya-tabanlı SQLite'a yazan iki GERÇEK OS thread'iyle
  test eder — gerçek bir `sqlite3.IntegrityError` üretir.
- **Başarısız doğrulamalar `AuditEvent`'e yazılır** (reddedilen tutar,
  para birimi, passthrough, status vb.) — ayrı, küçük bir commit ile (ana
  akışta henüz hiçbir yazma yapılmamış olsa da, ileride bu davranış
  değişirse diye kasıtlı olarak izole). Ham bvpay yanıtı ve kart bilgisi
  KAYDEDİLMEZ, yalnız hata sınıfı + `order_id`/`payment_id`/durum özeti.
- **`refunded`/`voided`, `declined`'dan ayrı bir hata sınıfı**
  (`PaymentRefundedOrVoided`) — ikisi de reddedilir ama iade/iptal durumu
  ileride "abonelik geri al" akışına (PLAN.md §7 F3) bağlanacağı için ayrı
  yakalanabilir olması gerekiyordu.
- **Abonelik uzatma:** `period_end = max(bugün, mevcut_bitiş) + ay`
  (PLAN.md §5.1 madde 4, birebir). Ay ekleme, hedef ayda gün taşarsa
  (31 Ocak + 1 ay) o ayın son gününe sabitler — `app/services/subscriptions.py::_add_months`.
- **`LisansImzalayici` protokolü** (`app/licensing.py`) korunuyor —
  `ege_lisans` artık hazır ve entegre (`EgeLisansImzalayici`), ama testler
  hâlâ `FakeImzalayici` kullanmaya devam ediyor (offline-activation'ın
  uçtan uca testi hariç, bkz. Testler). `EgeLisansImzalayici`, anahtar yolu
  (`EGE_LISANS_OZEL_ANAHTAR`) tanımsızsa ya da dosya yoksa AÇIK bir
  `RuntimeError` ile durur — sessizce imzasız lisans üretmez. Anahtar
  İÇERİĞİ sınıfın içinde hiç tutulmaz; her `imzala()` çağrısında dosyadan
  okunup `ege_lisans.signing.sign_payload`'a verilir, loglanmaz.
- **`ege_lisans` vendorlanmadı, yol bağımlılığı (`-e ../ege_lisans`) olarak
  eklendi** — README'de mapEGE/sisEGE/colEGE için "kaynak olarak
  vendorlanır" deniyor ama bu ÜRÜN İSTEMCİLERİ için (dağıtılan pakete
  gömülmeleri gerekiyor); portal sunucu tarafı ve tek bir yerde çalışıyor,
  vendorlamanın getirisi yok, editable kurulum güncellemeyi kolaylaştırıyor.
- **Çevrimdışı aktivasyon tek bir imzalı `license.json` üretir**
  (`POST /api/v1/subscriptions/{id}/offline-activation`,
  `app/services/offline_activation.py`) — abonelikteki HER ürün için tam
  olarak bir `activation_request` dosyası (ege_lisans'ın kendi ürettiği
  biçim) bekler, `ege_lisans.signing.build_v2_payload` ile ürün başına
  `tier` (her zaman `"full"`) + `fingerprint.components` taşıyan tek bir v2 belge kurar (paket
  satışında ürünler farklı makinelerde olabildiği için — bkz. ege_lisans
  README). IDOR koruması sisEGE'deki desenle aynı: abonelik yoksa VEYA
  başka bir müşteriye aitse ikisi de aynı 404'ü döner (bkz.
  `tests/test_offline_activation.py::test_baskasinin_aboneligine_erisim_404_doner`).
  Uçtan uca test ürettiği belgeyi GERÇEK `ege_lisans.validate_license`'a
  veriyor — sahte bir doğrulayıcı değil.
- **`ensure_license_key` ikiye ayrıldı** (`app/services/licenses.py`):
  `get_or_create_license_key` yalnız insan-okur `LicenseKey`'i garanti eder,
  imzalı belge ÜRETMEZ; `ensure_license_key` bunun üstüne (yalnız YENİ
  üretildiyse) ödeme akışının ihtiyaç duyduğu "online tarzı" placeholder
  `IssuedLicense`'ı (fingerprint yok) ekler. `payments.py` hâlâ
  `ensure_license_key` çağırıyor (davranışı BİREBİR aynı, testleri
  değişmeden geçiyor); `offline_activation.py` artık `get_or_create_license_key`
  kullanıyor ve kendi gerçek (fingerprint'li) `IssuedLicense`'ını kendisi
  yazıyor — bir önceki turda gözlemlediğim gereksiz çift-satır sorunu
  böylece kapandı (bir aboneliğin ilk lisans olayı çevrimdışı aktivasyon
  olsa bile artık tek satır).
- **Lisans kaçağı kapatıldı** (`app/services/offline_activation.py` —
  EGE lider'in incelemesinde bulundu): müşterinin yüklediği
  `activation_request` dosyası elle değiştirilebildiği için, yalnızca
  `hostname` (biricik olmayan, zayıf bir bileşen) içeren bir dosya
  gönderilirse `ege_lisans`'ın ÇAPA'sız (`instance_id`/`machine_id` yok)
  lisanslar için uyguladığı k-of-n kuralı devreye giriyordu — tek bir
  imzalı lisans aynı `hostname`'e sahip sınırsız kurulumda geçerli
  olabiliyordu. Düzeltme: `instance_id` artık HER ZAMAN zorunlu (ürün
  tarafından kalıcı üretilir, bulunamama durumu yok — bir ÇAPA bileşeni
  olduğu için lisansta bulunması k-of-n'e düşmeyi tek başına engelliyor).
  `machine_id` bilerek zorunlu TUTULMADI — `ege_lisans.fingerprint.
  _machine_id()` bazı ortamlarda (minimal Docker imajları, machine-id
  dosyası olmayan Linux, kısıtlı Windows) meşru biçimde `None` dönebilir;
  zorunlu tutmak bu kurulumları haksız yere reddederdi, `instance_id` tek
  başına açığı kapatmaya yetiyor (gerekçesi kod içinde de var). Ayrıca:
  yalnızca bilinen bileşen adları (`instance_id`/`machine_id`/`mac`/
  `hostname`) kabul edilir, değerler 64 karakter küçük harf hex (sha256
  biçimi) olmalı, dosya 16 KB'ı geçemez — hepsi 422. EGE lider ayrıca
  `ege_lisans`'ın kendisine de bir savunma katmanı (v2 lisanslarda çapa
  zorunluluğu) ekletiyor (worker_1 üzerinden) — bu portaldaki düzeltmenin
  YERİNE değil, YANINDA (savunma derinliği).
- **İkinci bir yol kapatıldı — bilinen "unknown" `instance_id`**
  (`app/services/offline_activation.py` — yine EGE lider'in incelemesinde
  bulundu): `instance_id`'yi zorunlu kılmak tek başına yetmiyordu —
  `ege_lisans.fingerprint._instance_id()`, veri dizini (`instance_file`)
  okunamaz/yazılamazsa sabit `"unknown"` döner; veri dizinini kasıtlı
  salt-okunur yapan bir müşteri HER kurulumda aynı
  `component_hash(product, "instance_id", "unknown")` değerini üretip
  yine sınırsız kopyalanabilir bir lisans elde edebilirdi. Düzeltme:
  - Gelen `instance_id`, o ürün için bilinen "unknown" hash'iyle
    karşılaştırılıyor — `ege_lisans.fingerprint.component_hash` burada da
    İTHAL EDİLİYOR, KOPYALANMIYOR; kontrol ürüne özgü (`component_hash`'in
    kendisi `product` parametresi aldığı için mapEGE'nin "unknown"
    hash'i sisEGE dosyasında normal bir değer gibi görünmüyor). Eşleşirse
    422 + "kurulum kimliği okunamadı, lisans veri dizininin yazılabilir
    olduğundan emin olun" mesajı.
  - Aynı `instance_id` hash'i BAŞKA bir müşterinin aktif (`revoked_at`
    boş) `Activation`'ında zaten varsa istek REDDEDİLMİYOR (yanlış
    pozitif riski var — iki müşteri gerçekten aynı durağan bir değere
    düşmüş olabilir), yalnızca `AuditEvent("activation.instance_id_collision")`
    yazılıyor — kurulum kimliği dosyasının kopyalanmış olabileceğinin
    sinyali, elle incelenir. Aynı müşterinin kendi tekrar aktivasyonu
    (ör. lisansı yeniden indirmesi) çarpışma SAYILMIYOR.
  - **Sınırlama:** bu katman, veri dizinini (instance_id dosyasını)
    makineler arasında KOPYALAYIP `machine_id`'yi silen KARARLI bir
    müşteriye karşı TAM koruma sağlamaz — o durumda `instance_id` hash'i
    GERÇEK ve BİRİCİK görünür (rastgele üretilmiş, "unknown" değil),
    yalnızca paylaşılmıştır; çarpışma denetimi bunu yakalayabilir ama
    reddetmez. Asıl kontrol çevrimiçi aktivasyondaki koltuk sayımı olacak
    (PLAN.md §6 — EGE lider ekleyecek). `ege_lisans` tarafında da
    (worker_1) "unknown" artık üretilmeyecek şekilde ayrıca düzeltiliyor;
    bu portaldaki katman ona bağımlı değil, kütüphanenin eski/güncel
    sürümlerine karşı da çalışır.
  - Testler: `tests/test_offline_activation.py` — bilinen kötü
    `instance_id` → 422, kötü hash'in ürüne özgü olduğu, çarpışmanın
    reddetmeden işaretlendiği (doğru `customer_id`'lerle), aynı
    müşterinin tekrar aktivasyonunun çarpışma sayılmadığı.
- **Gerçek oturum, sisEGE'nin `auth.py`'sindeki yaklaşımla (kopyalanmadı,
  ayrı yazıldı):** `get_current_user` hem `Authorization: Bearer` header'ını
  hem HttpOnly bir oturum çerezini kabul eder — tarayıcı tabanlı bir arayüz
  çerezi otomatik gönderir, script/API istemcileri bearer kullanır. Token
  `itsdangerous` (zaten bağımlılık) ile imzalanır/süresi kontrol edilir;
  sisEGE'nin kullandığı PyJWT'yi ayrıca eklemedim. İlk taslakta
  `POST /api/v1/orders` `customer_id`'yi QUERY PARAMETRESİ olarak alıyordu
  — herkes başkasının `customer_id`'siyle sipariş açabiliyordu (IDOR); EGE
  lider'in incelemesinde yakalandı. Artık `customer_id` HER ZAMAN
  `get_current_user`'ın döndürdüğü oturumdaki kullanıcıdan geliyor, istek
  gövdesinde/URL'de bir `customer_id` alanı hiç yok (bkz.
  `tests/test_orders.py::test_api_baskasinin_customer_id_gonderemez`).
- **Parolalar bcrypt ile saklanır** (`app/security.py`, sisEGE'yle aynı
  yaklaşım) — ilk taslakta stdlib PBKDF2-HMAC-SHA256 kullanmıştım (ek
  bağımlılık istemediğim için); EGE lider bcrypt'e geçmemi istedi, bcrypt
  zaten bu ortamda kurulu olduğu için sorun olmadı. Lisans anahtarları
  yine de düz SHA-256 ile hash'leniyor — onlar kullanıcı parolası değil,
  bizim ürettiğimiz yüksek entropili sırlar, yavaş bir KDF'e gerek yok.
- **`UTCDateTime` (`app/models.py`)** — eşzamanlılık testi yazarken ortaya
  çıkan bağımsız bir hata: SQLite (README'de önerilen geliştirme DB'si),
  `DateTime(timezone=True)` kolonlarını round-trip'te NAIVE döner (tzinfo
  kaybolur). Bu, `extend_subscription`'daki `max(now, sub.current_period_end)`
  gibi Python-seviyesi karşılaştırmaları taze bir session'da (yani her
  gerçek istekte) `TypeError` ile çökertiyordu — bir aboneliğe yapılan
  İKİNCİ ödeme SQLite'ta pratikte hep patlardı, testler bunu yakalamamıştı
  çünkü testlerin çoğu aynı session'ı (`flush`, `commit` değil) tekrar
  kullanıyordu. `UTCDateTime` bir `TypeDecorator`: okurken tzinfo eksikse
  UTC varsayarak düzeltir; PostgreSQL'de zaten no-op'tur.
- **Deneme (trial) lisansı** (PLAN.md §8 madde 7 — karar 2026-09-26:
  lisanssız kurulum ürüne gömülü 7 gün çalışır, worker_1/ürün tarafı; bu
  portal tarafı YALNIZ üreticinin süreyi değiştirip imzalı bir deneme
  lisansı ürettiği kısım):
  - **Süre çözümleme önceliği:** müşteri override (`Customer.
    trial_days_override`) > aktif kampanya (`TrialCampaign`, tarih
    aralığı) > genel varsayılan (`TrialSettings`, **DB'de bir satır**,
    env'de DEĞİL — üretici çalışma zamanında değiştirebilsin diye, bkz.
    `app/services/trial.py::resolve_trial_days`). Kampanyalar çakışırsa EN
    SON OLUŞTURULAN kazanır — basit, öngörülebilir; kesişmeme operasyonel
    bir beklenti, DB seviyesinde zorlanmıyor. Yöneticinin elle verdiği ek
    süre(ler) bunun SONUNA eklenir; **birikmeli** — tüketilmemiş TÜM
    `TrialGrant`'ların `extra_days`'i toplanır, bir deneme lisansı
    üretilince HEPSİ birlikte tüketilir (`consumed_at`, bkz.
    `find_usable_grants`) — bir yöneticinin verdiği hiçbir süre askıda
    kalmaz. Herhangi bir tüketilmemiş grant varsa "aynı müşteri+ürün için
    ikinci deneme yok" kuralı (yalnız o müşteri için) bir kez atlanır.
    Hepsi `AuditEvent`'e yazılır (`trial.settings_updated`/
    `campaign_created`/`customer_override_set`/`grant_created`/`issued`).
  - **Ayrı, Subscription'a bağlı OLMAYAN tablolar** (`TrialLicense`,
    `TrialActivation`) — mevcut `LicenseKey`/`Activation`/`IssuedLicense`
    NOT NULL bir `Subscription` FK'si gerektiriyor, deneme ise SATIN ALMA
    ÖNCESİ verilir. İki küçük paralel tablo, var olan abonelik şemasını
    nullable FK'lerle kirletmekten daha basit.
  - **Kötüye kullanım engelleri, çevrimdışı aktivasyondakiyle AYNI kod
    yolundan:** `activation_request` doğrulaması (`instance_id` zorunlu,
    bilinen bileşenler, hex biçimi, bilinen "unknown" hash reddi)
    `app/services/offline_activation.py`'den `app/services/
    activation_request.py`'ye ÇIKARILDI — hem çevrimdışı aktivasyon hem
    deneme lisansı AYNI fonksiyonu çağırıyor (kopyalama yok). Aynı
    müşteri+ürün için ikinci deneme → 409 (`DuplicateTrialError`).
  - **Çapraz-müşteri `instance_id` çarpışması: deneme REDDEDER, abonelik
    çevrimdışı aktivasyonu yalnız İŞARETLER — bilerek farklı (EGE lider
    onayladı).** Deneme tarafında (`InstanceIdAlreadyTrialedError`, 409 +
    `AuditEvent("trial.instance_id_collision")`): deneme öncesinde
    müşteriyle henüz gerçek bir ödeme ilişkisi/kanıtı yok, bu yüzden aynı
    kurulumun başka bir müşteride deneme aldığı görülünce doğrudan
    reddediyoruz. Abonelik çevrimdışı aktivasyonunda (bkz. yukarıdaki
    "Lisans kaçağı kapatıldı" maddeleri) müşteri ZATEN ÖDEMİŞ — orada
    yanlış pozitifle meşru, ödeyen bir müşteriyi kilitleme riski daha ağır
    bastığı için yalnız işaretlenir, reddedilmez. Yöneticinin grant'ı
    YALNIZ aynı-müşteri kuralını atlatıyor, çapraz-müşteri `instance_id`
    kontrolünü DEĞİL (kasıtlı — o ikinci kontrol bir kopyalama/paylaşım
    sinyali, tek bir müşteriye ek süre vermek bunu geçersiz kılmamalı).
  - **`license_type` artık `ege_lisans`'ın resmi parametresi** —
    `build_v2_payload(..., license_type="trial")` doğrudan çağrılıyor
    (worker_1 ekledi; önceki turda kütüphane henüz desteklemediği için
    payload'a manuel eklenen küçük bir sarmalayıcı vardı, kaldırıldı).
    `validate_license` sonucu da `license_type` alanını dönüyor — uçtan
    uca test artık BUNU da (kendi payload'ımızdan değil, gerçek doğrulama
    sonucundan) kontrol ediyor. Kütüphane ayrıca v2 lisanslarda
    `instance_id` çapasını KENDİSİ de zorunlu kılıyor artık
    (`"fingerprint_missing_anchor"`) — portalın kendi
    `activation_request.py` kontrolüyle aynı açığı kapatan, kütüphane
    tarafında BAĞIMSIZ bir ikinci katman.
  - **Tier "pro", grace_days 0** (PLAN.md §8 madde 7: "ürünün tamamı
    denensin"; deneme zaten kısa süreli olduğu için ek bir ek-süre
    toleransı anlamsız).
  - **`is_staff`, `User.role`'den TAMAMEN BAĞIMSIZ bir platform yetkisi
    — "rol karışıklığı" düzeltmesi (EGE lider'in incelemesinde bulundu).**
    İlk taslakta deneme ayarları gibi üretici-yalnız uçlar (`require_admin`)
    müşteri KURUMU İÇİ `User.role == ADMIN`'e bağlanmıştı — bu, bir
    müşteri kendi ekibine (kendi kurumu içinde, meşru biçimde) "admin"
    rolü verdiğinde o kullanıcının YANLIŞLIKLA tüm platformun deneme
    ayarlarına (başka müşterilere grant/override dahil) erişebilmesi
    demekti. Düzeltme: `User.is_staff` (bool, varsayılan `False`) eklendi,
    `role`'den bağımsız; `require_staff` (eski `require_admin`) yalnız
    buna bakıyor. `POST /auth/register` hâlâ her zaman `MEMBER` +
    `is_staff=False` oluşturuyor — personel hesabı self-servis hiçbir
    uçtan oluşturulamaz/yükseltilemez; `scripts/personel_olustur.py`
    (yeni CLI betiği) kullanılır. Parola argv'den ALINMAZ (kabuk
    geçmişinde görünür) — bir terminalde `getpass` ile sorulur, terminal
    yoksa stdin'in ilk satırından okunur. Var olan bir kullanıcıyı
    yükseltirken parola hiç sorulmaz/değiştirilmez. Test:
    `tests/test_trial_endpoints.py::test_musteri_ici_admin_role_uretici_uclarina_403_alir`
    — müşteri içi `role=ADMIN, is_staff=False` bir kullanıcının üretici
    uçlarına 403 aldığını doğruluyor.
- **`GET /api/v1/subscriptions` ve `GET /api/v1/subscriptions/{id}/licenses/
  {license_id}`** (2026-09-28 görevi — müşteri kendi aboneliklerini/
  lisanslarını görecek uç yoktu). `customer_id` istekten DEĞİL oturumdan
  gelir (aynı IDOR deseni, `app/routers/orders.py`); abonelik yoksa VEYA
  başka müşteriye aitse ikisi de aynı 404 (`_abonelik_getir`,
  `app/routers/activations.py`'deki ile aynı desen, kopyalanmadan tekrar
  yazıldı — iki satırlık kontrolü ayrı modüle çıkarmak bu ölçekte gereksiz).
  Liste ucu her abonelik için plan/kalemler, durum, `current_period_end`,
  aktivasyon özetleri VE verilmiş lisansların yalnızca ÖZETİNİ döner
  (`license_id`, `issued_at`, `expires_at`) — İMZALI `license.json`
  GÖVDESİ (payload/signature) listede YOK, yalnızca yeniden indirme
  ucunda. `license_id` ayrı bir kolon değil, `IssuedLicense.payload`
  içinde durduğu için `find_issued_license` (`app/services/licenses.py`)
  Python tarafında filtreler (abonelik başına tipik birkaç kayıt olduğu
  için SQL JSON sorgusuna gerek yok, hem SQLite hem PostgreSQL'de aynı
  şekilde çalışır). Yeniden indirme her çağrıda
  `AuditEvent("license.redownloaded")` yazar (`subscription_id`,
  `license_id`, `customer_id` ile) — kim ne zaman tekrar indirdiğinin izi.
- **İndirme merkezi — oturum açmış her kayıtlı müşteri, tüm aktif İMZALI
  sürümler** (2026-10-06 kararı). Abonelik ya da portal denemesi
  GEREKMEZ: kurulum kendi lisanssız 7 günlük denemesiyle başlar, asıl kapı
  ürünün içindeki kilittir. Eski kural ("aktif abonelik VEYA aktif portal
  denemesi") yeni bir müşteriyi kilitliyordu: portal deneme aktivasyonu
  (`POST /api/v1/trial-activation`) kurulmuş üründen gelen bir
  `activation_request` ister, ürünü indiremeyen müşteri onu üretemez.
  Kayıt zorunlu kalır ve her indirme `AuditEvent("release.downloaded")`
  (müşteri + sürüm) yazar. `entitled_product_ids` raporlama/ileride kademe
  kısıtı için duruyor ama indirme yolunda KULLANILMIYOR. İmzasız
  (`signed=False`) sürüm müşteriye ASLA görünmez/inemez — yalnız personel
  (`is_staff`). Olmayan, pasif ve (müşteri için) imzasız sürüm AYNI 404'ü
  döner (var-yok ayrımı sızdırmaz).
- **`Release.storage_key` yalnızca `resolve_release_path` ÜZERİNDEN
  çözümlenir** (`app/services/releases.py`) — üç bağımsız kontrol: mutlak
  yol/`..` bileşeni reddi, çözümlenmiş yolun depolama kökünün GERÇEKTEN
  altında kaldığının doğrulanması (`Path.resolve()` + `relative_to`), VE
  kökten dosyaya giden hiçbir ara bileşenin (dosyanın kendisi dahil)
  sembolik bağ OLMADIĞININ doğrulanması — ikinci kontrol tek başına
  yeterli olurdu ama üçüncüsü, kök altında kalan ama başka bir müşterinin
  dosyasına işaret eden bir sembolik bağı da yakalar. Bir hata, iç yolu/
  sebebi istemciye SIZDIRMADAN sabit bir 500 döner (`app/routers/
  downloads.py::surumu_indir`) — `storage_key` normalde yalnız
  `scripts/surum_yayinla.py` tarafından yazılır, ama DB satırı bir şekilde
  bozulsa bile indirme ucu güvenli şekilde başarısız olmalı.
- **Sürüm yükleme API'den DEĞİL, yalnız `scripts/surum_yayinla.py`
  CLI'sıyla** — SHA-256/boyutu kendisi hesaplar (istemcinin bildirdiğine
  güvenilmez), dosyayı `PORTAL_RELEASE_DIR` altına kopyalar, `Release`
  kaydını açar. `--personel <e-posta>` zorunlu: aktif bir `is_staff`
  hesabı olmalı, `Release.created_by_user_id`'ye ve
  `AuditEvent("release.published")`'e yazılır.
- **Yayından kaldırma: `POST /api/v1/admin/releases/{id}/deactivate`**
  (personel, `{"reason": "..."}` zorunlu). Satırı SİLMEZ, `is_active=False`
  yapar — müşteri listesinden düşer, indirme 404 döner; geçmiş indirme
  kayıtları kalır. `AuditEvent("release.deactivated")` gerekçeyle yazılır;
  zaten pasif sürüm 409.
  `--unsigned` TEK BAŞINA yetmez, `--imzasiz-onay` ile BİRLİKTE verilmesi
  gerekir (`personel_olustur.py`'deki gibi bir CLI betiği, self-servis bir
  uç DEĞİL) — yanlışlıkla imzasız bir paketin (ya da tersi) fark edilmeden
  yayınlanmasına karşı kasıtlı bir sürtünme. Aynı ürün+sürüm+paket türü
  ikinci kez yayınlanmaya çalışılırsa (UNIQUE kısıtı) açık bir hatayla
  reddedilir, yarım bırakılmış bir DB satırı/dosya kalmaz (DB satırı önce
  `flush()` ile denenir, yalnız başarılıysa dosya kopyalanır).
- **Havale/EFT: personel elle "ödendi" işaretler** (kullanıcı kararı,
  2026-10-05 — bvpay banka bilgilerini beklerken, bkz. PLAN.md §8 madde 5).
  `POST /api/v1/admin/orders/{id}/mark-paid` (`is_staff`): `Order`
  `SELECT ... FOR UPDATE` ile kilitlenir; **görevler ayrılığı** — personelin
  kendi müşteri kaydı siparişin müşterisiyle AYNIYSA REDDEDİLİR; sipariş
  `PENDING` değilse (bvpay ile zaten ödenmiş dahil) 409; gönderilen tutar
  `order.total`'a (KDV dahil) `Decimal` TAM EŞİT olmalı — KISMİ ÖDEME YOK;
  `bank_reference` boş olamaz ve `Payment.bank_reference` UNIQUE kısıtıyla
  (DB seviyesinde, yarışa karşı GERÇEK güvence — bkz. `tests/
  test_postgres_yaris.py::test_ayni_siparisi_iki_personel_eszamanli_isaretler`)
  sistem genelinde tekildir; `received_at` gelecekte olamaz. Onaylandıktan
  SONRAKİ etkiler (abonelik uzatma + lisans üretme)
  `app/services/payments.py::apply_payment_effects` ÜZERİNDEN bvpay
  akışıyla AYNI fonksiyonu paylaşır — kopya mantık yazılmadı, bvpay
  davranışı birebir kaldı (bu, `PaymentVerificationService.
  verify_and_process`'in inline mantığından ÇIKARILDI). Reddedilen HER
  deneme (`payment.mark_paid_rejected`) ve başarılı işaretleme
  (`payment.marked_paid_manual`) `AuditEvent`'e yazılır.
  `Payment.bvpay_payment_id` bu yüzden NULLABLE oldu (havale/EFT'te bvpay
  hiç devreye girmiyor) — migration SQLite'ta düz `ALTER COLUMN`
  desteklenmediği için `batch_alter_table` ile yapıldı (KDV migration'ındaki
  AYNI SQLite-güvenlik gerekçesi). Frontend: `is_staff` yalnız `TokenResponse`
  üzerinden GÖRÜNTÜ amaçlı taşınır (`StaffRoute.tsx` — personel değilse
  sessizce 404, var olmayan bir rotaymış gibi); gerçek yetki HER ZAMAN
  backend'deki `require_staff`dir.
- **Canlıya hazırlık — güvenlik sertleştirmesi** (2026-10-05, portal
  internete açılacak): Bkz. "Canlıya alma" bölümü için dağıtım, burada
  YALNIZ uygulama içi kararlar.
  - **Brute-force hız sınırlaması** (`app/services/auth_throttle.py`,
    `LoginAttempt` tablosu) — Redis YOK, DB tablosu (tek VE çok süreçli
    dağıtımda AYNI şekilde doğru). Kayan 15 dk pencere, 5 başarısız/pencere;
    e-posta VE IP AYRI AYRI sayılır. Kilitliyken de "e-posta veya parola
    yanlış" — AYNI genel hata (kilitli/yanlış ayrımı sızdırılmaz).
    Bilinmeyen bir e-postada da GERÇEK bir bcrypt karşılaştırması çalışır
    (`verify_password_or_dummy`, sabit bir sahte hash'e karşı) — zamanlama
    var-olan-ama-yanlış-parolalı bir denemeyle AYNI büyüklükte kalır (user
    enumeration'a karşı). Kayıtta IP başına ayrı bir sınır (başarı/başarısız
    FARK ETMEZ, her deneme sayılır).
  - **CSRF** (`app/middleware.py::OriginDogrulamaMiddleware`) — oturum
    çerezi artık `SameSite=Strict` (frontend AYNI origin'den sunuluyor,
    bkz. aşağı); İKİNCİ, bağımsız bir katman olarak durum değiştiren HER
    istekte `Origin` (yoksa `Referer`'den türetilen) `ALLOWED_ORIGINS`'te
    OLMALI, aksi halde 403. `/webhooks/bvpay` muaf — sunucudan sunucuya
    gelir, Origin/Referer hiç taşımaz, asıl doğrulama zaten GERİ bir `GET`
    ile yapılıyor (gövdeye/başlığa güvenilmiyor olması bu istisnayı
    güvenli kılıyor).
  - **Parola politikası** (`app/security.py`) — en az 12 karakter, en çok
    72 BAYT. Üst sınır keyfî DEĞİL: bcrypt (bu projedeki 4.x sürümü) 72
    bayttan sonrasını SESSİZCE KESİYOR (hata vermiyor, elle doğrulandı) —
    kullanıcı uzun bir parola girip güvende sandığı hâlde 73. bayttan
    sonrası doğrulamada hiç ÖNEMLİ DEĞİL; sessizce kesmek yerine AÇIKÇA
    reddediyoruz. `scripts/personel_olustur.py` AYNI politikayı uygular.
  - **Başlangıç reddi** (`app/startup_checks.py`, sisEGE'nin
    `startup_checks.py`'sindeki AYNI desen) — `ENVIRONMENT=production`
    iken `SECRET_KEY` boş/bilinen-varsayılan OLAMAZ, `COOKIE_SECURE=true`
    OLMALI; biri eksikse süreç HİÇ AÇILMAZ (`sys.exit(1)`,
    `app/main.py`da import anında çalışır). `development`'ta (varsayılan)
    hiçbir kontrol çalışmaz.
  - **Güvenlik başlıkları** CSP/X-Content-Type-Options/Referrer-Policy/
    frame-ancestors — backend'DE DEĞİL, `deploy/Caddyfile`'da (frontend'i
    sunan TEK katman, bkz. aşağı) — `style-src 'unsafe-inline'` gerekli
    (React `style={{...}}` inline stil kullanıyor, `<script>` ile AYNI
    kategori DEĞİL), `script-src` ise saf `'self'` (build çıktısı inline
    `<script>` içermiyor).

## Canlıya alma

Portal internete açık (karşılaştırma: sisEGE'den DAHA sert bir güvenlik
duruşu gerekiyor, bkz. yukarıdaki "Canlıya hazırlık" maddesi). Mimari: tek
origin — Caddy (`deploy/Caddyfile`) otomatik HTTPS ile `app` servisine
(backend + aynı imajdan sunulan frontend statik dosyaları, `app/main.py`
SPA sunumu) ters vekillik yapar; `app` yalnız `127.0.0.1`e bağlıdır (host
dışından doğrudan erişilemez), veritabanı (PostgreSQL 16) ise hiç dışarı
açılmaz.

```
İnternet → Caddy (80/443, otomatik HTTPS) → app:8002 (backend + SPA) → db:5432 (PostgreSQL, dışa kapalı)
```

### Dosyalar (`deploy/`)

| Dosya | İşlev |
|---|---|
| `Dockerfile` | Çok aşamalı build: frontend (`node:22-alpine`) → backend (`python:3.12-slim`), non-root kullanıcı, `/healthz` healthcheck. **Build context `ege_portal/`DEĞİL, bir üst dizin** (`ege_platform/`) — `requirements.txt`'teki `-e ../ege_lisans` kardeş bir `ege_lisans/` dizini gerektirir (bkz. Dockerfile başlığındaki not). |
| `entrypoint.sh` | `alembic upgrade head` → `uvicorn` (bu sırayla — şema HER ZAMAN uygulamadan önce). Migration başarısız olursa süreç BAŞLAMAZ. |
| `docker-compose.yml` | `db` (Postgres 16, kalıcı volume, dışa açık port YOK) + `app` (yalnız `127.0.0.1` port eşlemesi, kalıcı `portal_releases` volume'ü, özel anahtar salt-okunur bağlanır) + `caddy` (80/443 dışa açık, otomatik HTTPS). Sırlar `${VAR:?...}` — tanımsızsa compose AÇIKÇA hatayla durur. |
| `Caddyfile` | Otomatik HTTPS (`{$PORTAL_DOMAIN:portal.bigventus.com}`) + güvenlik başlıkları + `reverse_proxy app:8002`. |
| `.env.deploy.example` | `deploy/.env` olarak kopyalanacak sır şablonu. |

### Kurulum

```bash
cd ege_portal/deploy
cp .env.deploy.example .env
# .env'i doldurun: POSTGRES_PASSWORD, SECRET_KEY (openssl rand -hex 32),
# BVPAY_URL/BVPAY_API_KEY, EGE_LISANS_PRIVATE_KEY_PATH, PORTAL_DOMAIN
docker compose up -d --build
```

`PORTAL_DOMAIN` (varsayılan örnek: `portal.bigventus.com`) için gerçek DNS
A kaydı bu sunucunun IP'sine işaret ETMELİDİR — Caddy'nin Let's Encrypt
doğrulaması (ACME HTTP-01) buna bağlıdır; bu betikler GERÇEK bir DNS/sertifika
işlemi YAPMAZ, yalnızca Caddy'yi (kendisi sertifikayı otomatik alıp
yeniler) yapılandırır.

### Yedekleme

```bash
# Veritabanı (mantıksal dump):
docker compose exec -T db pg_dump -U ege_portal ege_portal | gzip > yedek-$(date +%Y%m%d).sql.gz
# İndirilebilir sürümler (PORTAL_RELEASE_DIR):
docker run --rm -v ege_portal_portal_releases:/veri:ro -v "$(pwd)":/yedek alpine \
    tar czf /yedek/surumler-$(date +%Y%m%d).tar.gz -C /veri .
```

`EGE_LISANS_PRIVATE_KEY_PATH`teki özel anahtar dosyası AYRI, offline bir
yedekte (kasa vb.) tutulmalı — konteyner/volume yedeklemesinin KAPSAMI
DIŞINDA, kasıtlı (host dosya sistemi, salt-okunur bağlanır).

## Kapsam dışı bırakılanlar (bilerek)

- **Checkout (ödeme başlatma) ucu ve mutabakat görevi BEKLETİLDİ** — EGE
  lider'in açık talimatı: bvpay'in kart bilgisini uygulamadan mı
  (`storetype=3d`, PCI-DSS kapsamına sokar) yoksa banka sayfasından mı
  (`3D_Pay_Hosting`) alacağı netleşmeden kart verisi alan bir uç
  yazılmayacak. `BVPayClient.create_payment` istemci olarak hazır ve test
  edilebilir (`FakeBVPayClient.create_payment`), onu çağıran portal ucu
  yok. Mutabakat görevi de aynı nedenle ertelendi;
  `PaymentVerificationService.verify_and_process(order_id, payment_id)`
  zaten doğrudan çağrılabilir durumda, yalnızca hangi `payment_id`'nin
  hangi siparişe ait olduğunu (webhook hiç gelmediyse) izleyecek bir
  mekanizma eksik.
- **Çevrimiçi aktivasyon (F4)** — anahtar girişi + günlük yenileme ucu,
  koltuk/makine limiti ZORLAMASI yok. `Subscription.seats` alanı ve
  `activation.mode="online"` şema desteği hazır ama hiçbir yerde
  sayılmıyor/sınırlanmıyor — PLAN.md §8 madde 3 (birim kurulum mu kurum mu,
  `SERVICE_ROLE` çok sunuculu kurulum nasıl sayılacak) kullanıcıya
  soruldu, karar gelmeden zorlama eklemedim.
- **İndirme merkezi (F5) — yalnız temel uçlar bu turda bitti** (2026-10-05):
  `GET /api/v1/downloads` (hakkı olunan ürünlerin aktif sürümleri) ve
  `GET /api/v1/downloads/{release_id}` (dosya akışı). PLAN.md §5.4'teki
  "kısa ömürlü imzalı URL" YOK — indirme doğrudan oturum doğrulamasının
  (`get_current_user`) ARKASINDA, kalıcı bir URL'den akıyor; imzalı/kısa
  ömürlü URL (ör. CDN'den dolaylı indirme) istenirse ayrı bir tur. Yükleme
  YALNIZ `scripts/surum_yayinla.py` CLI'sıyla — API'den dosya yükleme bu
  turda yok (kasıtlı, personel-yalnız bir akış; kötü niyetli/yanlış bir
  dosyanın API üzerinden yüklenme yüzeyini şimdilik tamamen kapatıyor).
- **Reddedilen/yinelenen ödemelerin elle iade akışı yok** — `Payment`
  satırları `processed_at=None` ile "iade gerekiyor" olarak işaretleniyor
  (bkz. `payment.duplicate_for_order` / `payment.verification_failed`
  audit olayları) ama bunları listeleyip iade tetikleyecek bir yönetici
  ucu henüz yok (PLAN.md §7 F3 kapsamı).
- **Deneme lisansını elle iptal/revoke eden bir uç yok** —
  `TrialActivation.revoked_at` modelde var (abonelik tarafındaki
  `Activation` ile tutarlı olsun diye) ama hiçbir yerde set edilmiyor;
  kötüye kullanan bir kurulumu manuel kapatmak için (ör. çapraz-müşteri
  çarpışma tespit edilince) bir yönetici ucu istenirse eklenmeli.
- **Deneme listeleme/görüntüleme ucu yok** — bir müşterinin/kurulumun
  daha önce deneme alıp almadığını görmek için yalnız `AuditEvent`/DB'ye
  bakılabilir, `GET /api/v1/admin/trials` gibi bir liste ucu bu turda
  eklenmedi (istenmemişti).

## Açık sorular (PLAN.md'ye eklemedim, karar sizde)

Önceki turlarda sorulanlardan KDV/tek-plan-id/oturum-IDOR/audit-log/
IssuedLicense-çift-satır/lisans-kaçağı (hostname'li ve "unknown"
instance_id'li aktivasyon istekleri)/çapraz-müşteri-tutarlılığı (deneme
reddeder, abonelik işaretler — kasıtlı, onaylandı)/`TrialGrant` tüketim
sırası (birikmeli oldu) kararlaştırıldı-veya-çözüldü; `with_for_update()`'in
gerçek PostgreSQL'de işlediği `tests/test_postgres_yaris.py` ile doğrulandı.
Kalan açık sorular:

1. **Makine/koltuk limiti** (PLAN.md §8 madde 3) — `Subscription.seats`
   alanı hazır ama hiçbir uç bunu okumuyor/zorlamıyor. Karar gelince
   çevrimiçi aktivasyon (F4) VE çevrimdışı aktivasyon ikisi de bunu
   uygulamalı — şu an çevrimdışı tarafta sınırsız sayıda aktivasyon kaydı
   oluşturulabilir. Bu, veri dizini kopyalama senaryosuna karşı da ASIL
   kontrol olacak (bkz. yukarıdaki "İkinci bir yol kapatıldı" maddesindeki
   sınırlama notu).
2. **Checkout ucu ve mutabakat görevi ne zaman?** bvpay'in
   kart-uygulamada-mı/3D_Pay_Hosting kararı netleşince mi, yoksa mock
   modda (3D_Pay_Hosting'siz, yalnız geliştirme için) önce mi eklensin?
3. **Çevrimiçi aktivasyon (F4) henüz başlanmadı** — anahtar girişi +
   günlük yenileme ucu. Kullanıcı şimdilik ertelenmesini istedi (koltuk
   limiti kararı ve checkout ucu gibi ön koşulları hâlâ açık).
4. **Personel (`is_staff`) hesabı yönetimi yalnız CLI'da
   (`scripts/personel_olustur.py`)** — bir yönetici arayüzünden personel
   ekleme/çıkarma ucu yok (bilerek: platform-genelinde yetki vermek
   self-servis bir uçtan yapılabilir bir şey olmamalı diye düşündüm, ama
   isterseniz `require_staff` arkasında bir uç eklenebilir).
