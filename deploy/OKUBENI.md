# deploy/ — işletim notları

Genel kurulum ve yedekleme: `../README.md` "Canlıya alma". Bu dosyada
yalnızca **üretim lisans imza anahtarı** runbook'u var.

## Üretim anahtarı

**Karar (2026-10-10):** EGE üretim lisans imza anahtarı **portal sunucusunda**
üretilir ve orada **parolayla şifreli** bir dosyada durur. Çevrimdışı (USB /
kasa) bir yedek kopya da tutulur. Bu anahtar mapEGE, sisEGE ve colEGE için
**ortaktır**: portal paket lisansını tek anahtarla imzalar, bu yüzden üç ürün
de aynı `PUBLIC_KEYS` listesini gömer (PLAN.md §6).

İki çift üretilir:

| Çift | Nerede | Ne zaman kullanılır |
|---|---|---|
| **birincil** | Portal sunucusunda (şifreli) + çevrimdışı iki kopya | Her gün; portal bununla imzalar |
| **yedek** | **Yalnız** çevrimdışı iki kopya (sunucudan silinir) | Birincil kaybolur ya da sızarsa |

Ürünler ikisinin açık anahtarını da gömer: `PUBLIC_KEYS[0]` = birincil,
`PUBLIC_KEYS[1]` = yedek. Ürünün lisans durumu hangi anahtarla doğrulandığını
`key` alanında raporlar: `"birincil"` ya da `"yedek-1"`. Bu davranış
`ege_lisans` schema_v1/v2'de ve mapEGE `licensing.py`'de zaten var.

### Portal yapılandırması

| Değişken | Değer | Not |
|---|---|---|
| `EGE_LISANS_OZEL_ANAHTAR` | `/run/secrets/ege_lisans_ozel_anahtar` | Şifreli PKCS8 PEM'in yolu. |
| `EGE_LISANS_ANAHTAR_PAROLA_DOSYASI` | `/run/secrets/ege_lisans_anahtar_parola` | Parolayı içeren dosyanın yolu. Sondaki satır sonu atılır. |
| `EGE_LISANS_ANAHTAR_KIMLIGI` | `birincil` \| `yedek` | Etikettir: açılışta loglanır, geçersiz değer reddedilir. |
| `EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI` | `sha256:<16 hex>` | Yüklenen anahtar bununla eşleşmezse portal başlamaz. Compose'da zorunlu. |

Host tarafında `deploy/.env` şunları içerir:

- `EGE_LISANS_PRIVATE_KEY_PATH`: şifreli PEM'in host yolu
- `EGE_LISANS_PASSWORD_FILE_PATH`: parola dosyasının host yolu

İkisi compose `secrets:` ile konteynerin `/run/secrets/` dizinine
**salt-okunur** bağlanır. Named volume'e yazılmaz, imaja girmez
(`.dockerignore` `*.pem` dosyalarını dışlar).

Güvenlik kuralları (`app/licensing.py`, `app/startup_checks.py`):

- **Env'de düz parola reddedilir.** `EGE_LISANS_ANAHTAR_PAROLA`,
  `EGE_LISANS_ANAHTAR_PAROLASI`, `EGE_LISANS_OZEL_ANAHTAR_PAROLA` ya da
  `EGE_LISANS_PAROLA` tanımlıysa imzalama yapılmaz, production'da portal
  başlamaz. Sebebi: env değerleri süreç listesinden ve `docker inspect`
  çıktısından görünür.
- **`ENVIRONMENT=production` iken anahtar şifreli olmalı.** Şifresiz anahtar
  reddedilir. Geliştirmede şifresiz anahtar kullanılabilir.
- **Anahtar açılışta bir kez yüklenir.** Bu her uvicorn worker'ı için ayrı
  ayrı olur. Parola yalnız yükleme süresince bir `bytearray`de durur, sonra
  sıfırlanır. Yükleme hatası portalı **başlatmaz**. Hata mesajı yalnız dosya
  yolunu ve nedeni içerir (bulunamadı / parola yanlış / şifresiz / parmak izi
  eşleşmiyor); parola ya da anahtar içeriği yazılmaz.

### 1. Üretim (portal sunucusunda, bir kez)

Ön koşul: Sunucu kurulmuş, imaj build edilmiş olmalı
(`docker compose build app` → `ege-portal:latest`). Bu adımlar root
olarak yapılır.

```bash
# Geçici üretim dizini — anahtarlar burada doğar
install -d -m 700 /root/ege_anahtar_uretim

# Aracı imajın içinde, root olarak, etkileşimli çalıştır
# (parolalar getpass ile iki kez sorulur, argümandan ALINMAZ)
docker run --rm -it --network none --user 0:0 \
  -v /root/ege_anahtar_uretim:/cikti \
  --entrypoint python ege-portal:latest \
  scripts/uretim_anahtari_olustur.py --cikti-dizini /cikti
```

Docker'sız alternatif: host'ta `pip install cryptography`, ardından
`python3 scripts/uretim_anahtari_olustur.py --cikti-dizini /root/ege_anahtar_uretim`.

Araç ne yapar:

- `ege_lisans_uretim_birincil.pem` ve `ege_lisans_uretim_yedek.pem`
  dosyalarını yazar. Her biri ayrı bir parolayla şifrelenir; parolalar en az
  16 karakter olmalı ve birbirinden farklı olmalı.
- Dosya izni 0600'dür, sahibi aracı çalıştıran kullanıcıdır. Windows'ta ACL
  yalnız o kullanıcıya izin verir.
- Var olan bir dosyanın **üzerine yazmaz**.
- Yazdığı her dosyayı parolasıyla geri açıp bir imza sınaması yapar.
- Şunları yazdırır:
  - açık anahtarlar (hex)
  - **parmak izleri**
  - ürünlerin `PUBLIC_KEYS` bloğu
  - `EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI` değeri

Özel anahtar ve parola **asla** yazdırılmaz.

Çıktıdaki açık anahtar bloğunu ve iki parmak izini kayda geçirin (bilet,
parola yöneticisi notu vb.). Bunlar gizli değildir.

### 2. Çevrimdışı yedek (aynı oturumda, hemen)

1. İki şifreli PEM'i **iki ayrı çevrimdışı ortama** kopyalayın (ör. USB-A
   kasada, USB-B ayrı bir lokasyonda).
2. Her kopyayı başka bir makinede parolasıyla açarak doğrulayın:
   `python -c "from cryptography.hazmat.primitives.serialization import load_pem_private_key as l; import getpass,sys; l(open(sys.argv[1],'rb').read(), getpass.getpass().encode()); print('OK')" dosya.pem`
3. **Parolaları anahtarlardan ayrı** saklayın (kurumsal parola yöneticisi
   ya da mühürlü zarf). Birincil ve yedek parolaları da ayrı yerlerde
   durmalı. Kural: hiçbir tek ortam hem bir PEM'i hem onun parolasını
   taşımaz.
4. **Yedek PEM'i sunucudan silin:**
   `shred -u /root/ege_anahtar_uretim/ege_lisans_uretim_yedek.pem`
   Yedek yalnız çevrimdışı kopyalarda kalır.

### 3. Portala kurulum

```bash
install -d -m 700 -o 1000 -g 1000 /srv/ege_sirlar
install -m 400 -o 1000 -g 1000 /root/ege_anahtar_uretim/ege_lisans_uretim_birincil.pem \
        /srv/ege_sirlar/ege_lisans_ozel_anahtar.pem

# Parola dosyası: ekrana/geçmişe düşmeden yazılır
( umask 077; read -rs -p "Birincil parola: " P; printf '%s' "$P" > /srv/ege_sirlar/ege_lisans_anahtar_parola; unset P; echo )
chown 1000:1000 /srv/ege_sirlar/ege_lisans_anahtar_parola && chmod 400 /srv/ege_sirlar/ege_lisans_anahtar_parola

shred -u /root/ege_anahtar_uretim/ege_lisans_uretim_birincil.pem && rmdir /root/ege_anahtar_uretim
```

Neden 1000:1000? İmajdaki `portal` kullanıcısının uid'i 1000'dir. Compose
dosya-tabanlı secret'ları host izinleriyle bind eder, yani root'a ait 0400
bir dosyayı portal okuyamaz.

`deploy/.env` dosyasına şunları yazın:

```
EGE_LISANS_PRIVATE_KEY_PATH=/srv/ege_sirlar/ege_lisans_ozel_anahtar.pem
EGE_LISANS_PASSWORD_FILE_PATH=/srv/ege_sirlar/ege_lisans_anahtar_parola
EGE_LISANS_ANAHTAR_KIMLIGI=birincil
EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI=sha256:...   # aracın çıktısından
```

Ardından `docker compose up -d` çalıştırın. Log'da şu satırı görmelisiniz:
`Lisans imza anahtarı yüklendi: kimlik=birincil parmak_izi=sha256:...`

Not: Parola dosyası sunucu diskinde durur. Bu bilinçli bir ödünleşimdir:
portal gözetimsiz yeniden başlayabilmelidir. Şifreleme, PEM'in tek başına
kopyalanmasına (ör. bir yedek ya da imaj sızıntısı) karşı korur; sunucunun
root'unu ele geçiren birine karşı korumaz. Daha güçlü koruma için ileride
KMS/HSM'e geçilebilir (PLAN.md §6).

### 4. Ürünlere açık anahtarın gömülmesi

Bu adım **tüm ürünlerde aynı anda** yapılır. Portal tek anahtarla paket
lisansı imzaladığı için ürünlerden biri farklı liste taşırsa o üründe
`invalid_signature` hatası alınır.

1. Aracın yazdırdığı `PUBLIC_KEYS` bloğunu (ilk iki satır: birincil, yedek)
   şu dosyalardaki geliştirme anahtarlarının **yerine** koyun:
   - mapEGE `geo_service/services/licensing.py::PUBLIC_KEYS`
   - sisEGE `license_service.py::PUBLIC_KEYS`
   - colEGE `license_service.py::PUBLIC_KEYS`

   Geliştirme anahtarları satılan derlemelerde **kalmaz**. Yorumdaki
   "(geliştirme)" etiketi "(üretim, sha256:...)" olur.
2. Her ürün derlemesinde gömülü anahtarların parmak izini
   (`sha256(bytes.fromhex(hex))[:16]`) kayıttaki değerlerle karşılaştırın.
   Portaldaki `EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI` değeri birincilin parmak
   izine eşit olmalı.
3. Üç üründe birden **yeni sürüm** çıkarın. Sahadaki eski sürümler yalnız
   geliştirme anahtarlarını tanır, üretim lisansını kabul etmez. İlk satıştan
   önce bu sürümler dağıtılmış olmalı.
4. Testlerin geliştirme lisansı akışı (`gelistirme_lisansi_uret.py`) üretim
   derlemesinde artık geçersizdir. Bu beklenen davranıştır.
5. Kabul testi: portal ile gerçek bir deneme/çevrimdışı lisans üretin, üç
   üründe yükleyin. Durum `valid` olmalı, `key` alanı `"birincil"` olmalı.

**Dikkat:** `PUBLIC_KEYS` listesi sahadaki kurulumlarda sonradan
genişletilemez. Yedek anahtar, ilk sürümden **önce** gömülmüş olmalı. Bu
yüzden iki anahtar birlikte üretilir.

### 5. Yedek anahtara geçiş (birincil kayboldu ya da sızdı)

Ürünlerin sahadaki sürümleri yedeği zaten tanıdığı için **yeni ürün sürümü
gerekmeden** imzalama sürdürülebilir.

1. Kasadan yedek PEM'i ve ayrı yerden yedek parolayı alın.
2. Bölüm 3'teki adımlarla yedeği kurun:
   - `/srv/ege_sirlar/ege_lisans_ozel_anahtar.pem` dosyasını yedek PEM ile
     değiştirin (1000:1000, 0400)
   - parola dosyasını yedek parolayla yeniden yazın
3. `deploy/.env` dosyasını güncelleyin:
   - `EGE_LISANS_ANAHTAR_KIMLIGI=yedek`
   - `EGE_LISANS_ACIK_ANAHTAR_PARMAK_IZI=<yedeğin parmak izi>`

   Dosya yollarını değiştirmek de yeterlidir. Kimlik etiketi ve parmak izi,
   yanlış dosyanın bağlanmasını önler.
4. `docker compose up -d app` ile portalı yeniden başlatın. Log'da
   `kimlik=yedek` görünmeli. Ürünler yeni lisanslarda `key: "yedek-1"`
   raporlar.

### 6. Senaryolar

**Birincil kayboldu, sızma yok** (disk arızası, parola unutuldu ve
çevrimdışı kopyası da yok):

- Çevrimdışı kopya varsa onu geri kurun (bölüm 3). Bitti.
- Kopya da yoksa bölüm 5'i uygulayın.
- Ardından, ürünlerin sonraki planlı sürümünde yeni bir yedek slotu
  hazırlayın: aracı yeni bir önek/dizinle çalıştırın. Bu durumda yeni
  `PUBLIC_KEYS` listesi şöyle olur: eski yedek **birincil** olur, yeni çift
  yedek olur. Bu sürüme kadar tek anahtara bağımlısınız; bunu kayda geçirin.

**Birincil sızdı** (PEM ve parolası birlikte ele geçirildi, ya da bundan
şüpheleniliyor):

1. **Hemen** bölüm 5'i uygulayın. Portal artık yalnız yedekle imzalar.
2. Sızan anahtarla sahte lisans üretilebilir ve sahadaki sürümler bu
   anahtarı tanımaya devam eder. Sızan anahtarı ürünlerden çıkarmanın tek
   yolu **yeni ürün sürümüdür**:
   - Aracı yeni bir dizinle çalıştırıp yeni bir çift üretin.
   - Üç üründe aynı anda `PUBLIC_KEYS` = (eski yedek, yeni yedek) yapın.
   - Sızan birincil listeden **silinir**.
   - Yeni sürümleri yayınlayın, müşterileri güncellemeye yönlendirin.
3. **Yeniden imzalama:** Yeni sürüme geçen müşterilerin sızan anahtarla
   imzalı lisansları artık doğrulanmaz.
   - Portal, aktif abonelikler için yeni anahtarla lisansı **yeniden
     üretmelidir**. Çevrimdışı müşteri için: yeni `activation_request` →
     yeni lisans. Çevrimiçi müşteri (F4) için: günlük yenileme bunu
     kendiliğinden yapar.
   - Bu akış için toplu bir yeniden imzalama aracı henüz yok. Bu senaryoda
     yazılması gerekir; abonelik ve aktivasyon kayıtları portal
     veritabanında durduğu için mümkündür.
4. Olayı kayda geçirin. Sızan PEM'in bulunduğu tüm ortamları ve parolalarını
   imha edin ya da değiştirin.

**Yedek sızdı:** Birincil çalışmaya devam eder. Bir sonraki ürün sürümünde
yeni bir yedek üretin ve `PUBLIC_KEYS[1]`'i değiştirin. Sızan yedeği
sahadaki eski sürümler tanımaya devam eder; bu risk ancak güncellemeyle
kapanır.

**Parola dosyası sızdı, PEM sızmadı:** PEM'i yeni bir parolayla yeniden
şifreleyin. Bunu çevrimdışı bir makinede yapın ve `cryptography` ile
`BestAvailableEncryption` kullanın. Ardından portaldaki dosyaları ve
çevrimdışı kopyaları değiştirin. Anahtarın kendisi değişmez, ürünlere
dokunulmaz.

### 7. Yeniden imzalama

Anahtar değişince eski lisanslar, ürün o anahtarı tanıdığı sürece geçerli
kalır. Yalnız ürün listesinden bir anahtar **çıkarıldığında** (yalnız sızma
senaryosunda) aktif aboneliklerin lisansları yeni anahtarla yeniden
üretilmelidir (bkz. bölüm 6). Normal yedeğe geçişte yeniden imzalama
**gerekmez**.
