# Jira Test Studio

Python 3.11+ ve Tkinter ile çalışan Türkçe masaüstü uygulaması. Jira test motoru
Playwright’tır; arayüz mevcut CLI, YAML şeması ve pytest entegrasyonunu kullanır.

## Başlatma

Windows Python kurulumunda **Tcl/Tk and IDLE** seçili olmalıdır. Repo kökünde:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m tkinter
run-gui.bat
```

Sonraki açılışlarda `run-gui.bat` dosyasına çift tıklayın. Başlatıcı mevcut `.venv`
ortamını kullanır, paketleri kendiliğinden kurmaz. Alternatif:

```text
python -m jira_test gui --workspace /path/to/workspace
```

`python -m tkinter` pencere açmıyorsa kullanılan Python’da Tk desteğini etkinleştirin;
sanal ortamı Tk destekli Python ile oluşturun. CLI kullanıcılarının Tk kurması gerekmez.
Linux’ta dağıtımın Tk paketi ve grafik oturumu gerekir. Chrome/Edge sistemde kurulu
olmalıdır; Firefox için `python -m playwright install firefox` kullanılır.

## İlk deneme

1. **Başlangıç → Çevrimdışı demo yükle** seçin. `studio-demo` klasörüne örnek katalog
   ve senaryo kopyalanır; mevcut örnek dosyaların üzerine yazılmaz.
2. **Test çalıştırma → Seçilenleri çalıştır** seçin. Katalog zorunluluk testi Jira’ya
   bağlanmadan çalışır.
3. **Sonuçlar ve hatalar** ekranında koşuyu ve test satırını seçin. Sonuç, adımlar,
   beklentiler, hata ayrıntıları ve olay günlüğü gösterilir.

## Bağlantı ve keşif

**Bağlantı ve profiller** ekranında HTTPS Jira adresi, farklı kaynak/test projeleri,
tarayıcı, zaman aşımı, TLS CA dosyası, ekran görüntüsü ve örnek sınırını düzenleyin.
Varsayılan alanlar, örnek kayıtlar ve CSS seçiciler gelişmiş YAML eşlemeleriyle girilir.
Profiller çalışma klasörünün `.jira-test-studio/profiles` dizinine kaydedilir;
`config.local.yaml` dahil mevcut config dosyaları açılabilir.

Kullanıcı adı ve parola yalnız bellekte tutulur; profil dosyasına yazılmaz.
`JIRA_USERNAME`/`JIRA_PASSWORD` varsa başlangıç değerleri alınır. Worker’a kimlik
bilgileri komut satırı yerine stdin borusundan iletilir. Günlük ve hata metinleri maskelenir.

**API kontrolü** ve **API + tarayıcı kontrolü** bağlantıyı sınar. **Jira keşfi** ekranında
kaynak veya test projesini, yalnız API ya da API + UI keşfini seçin. JSON katalogları
sonradan açabilir, üretilen HTML raporu görüntüleyebilirsiniz. İş türü, ekran, statü,
geçiş, kaynak ve serbest metin filtreleri alanları daraltır. Gözlem ayrıntılarında
seçenekler, şema ve keşfin ulaşamadığı kapsam görünür.

`unknown`, doğrulanmış `false` değildir. Kaynak/test projesi kimlikleri otomatik
eşleştirilmez. Seçili gözlemden oluşturulan taslak bağlamı korur; görünürlük bilinmiyorsa
beklenti açıkça sorulur.

## Test oluşturma

**Test tasarımcısı**, tek dosyada bir veya çok senaryo düzenler. Kimlik, açıklama,
fixture modu, iş türü, alanlar, parent ve statüye ulaşan geçiş yolu düzenlenebilir.
Adım/beklenti diyalogları motorun tüm eylem ve kontrollerini sunar. Değer türleri
metin, sayı, boolean, null, liste ve nesnedir; karmaşık değerler etiketli JSON
editöründe girilir. Adımları ekleyebilir, düzenleyebilir, kopyalayabilir ve sıralayabilirsiniz.

**YAML** sekmesindeki metin doğrulanıp görsel modele uygulanır. Geçersiz taslak
önceki geçerli modeli bozmaz ve kaydedilemez. Ham YAML kaydı yorumları korur;
görsel düzenleme sonrası YAML yeniden üretilirken yorum/biçim değişikliği bildirilir.
Kaydetme atomiktir; kaynak değiştirme ve kapatmada kaydedilmemiş değişiklikler sorulur.

## Test çalıştırma

Dosya veya klasör ekleyin. YAML dosyalarındaki her senaryo ve Python pytest testinin
her nodeid’si ayrı seçilebilir. Python test toplama ayrı süreçte çalışır; workspace
`conftest.py` fixture’ları korunur. Aynı anda tek toplama/keşif/koşu yapılır.

Workspace dışındaki Python dosyaları da mutlak dosya yolu ve test seçicisiyle
çalıştırılır; parametrik test seçimi yeniden çalıştırmada korunur. Çalıştırma
ekranı gönderilecek isteğin Jira adresini ve test projesini gösterir. Geçmiş
koşu yeniden başlatıldığında geçmiş ayarların kullanıldığı ayrıca belirtilir;
aktif koşunun hedefi profil düzenlense bile değişmez.

Canlı testler **test projesinde kayıt oluşturabilir ve değiştirebilir**. Oluşturulan
kayıtlar raporlanır, otomatik silinmez. Katalog testleri bağlantısız çalışabilir.
Durdurma, devam eden isteği yarıda kesmeden sonraki güvenli kontrol noktasında uygulanır;
yapılmış Jira değişiklikleri geri alınmaz. Uzun süren bir Python testi mevcut test
bitene kadar durdurmayı geciktirebilir. Arayüz yanıt vermeye devam eder.

## Sonuçlar ve yeniden çalıştırma

Her koşu `.jira-test-studio/runs/<run-id>` altında ayrı saklanır:

- `manifest.json`: seçim, ayarlar, kaynak bağlantıları ve koşu durumu.
- `snapshots/`: seçilen YAML, ilgili katalog ve Python kaynak kopyaları.
- `events.jsonl`: canlı olay günlüğü.
- `test-results.json`, `junit.xml`: test sonuçları ve hata kanıtları.

CLI ve GUI, setup/call/teardown aşamalarından aynı nihai test sonucunu üretir.
Teardown hatası başarılı test gövdesini başarısız kılar; çalıştırılmamış testler
başarılı sayılmaz. Python testlerinin yüklenmesi sırasında oluşan hata ve atlama
mesajları da JUnit yazılmadan önce kimlik bilgileri açısından maskelenir.

Sonuçtan kaynağı düzenleyebilir, ekran görüntüsünü/koşu klasörünü ve oluşturulmuş Jira
kaydını açabilirsiniz. Eksik raporlar başarı sayılmaz. Tümü veya yalnız başarısız /
engellenmiş testler yeniden çalıştırılabilir. YAML yeniden koşuları saklanan senaryo
ve katalog kopyalarını kullanır. Python testleri fixture/import davranışını korumak
üzere mevcut kaynakta çalışır; kaynak/conftest değişmişse önce bildirilir.

Ekran görüntüleri isteğe bağlıdır ve Jira ekranındaki hassas verileri içerebilir.
Koşu çıktılarının erişimini Jira verilerinizle aynı hassasiyette yönetin.

## Doğrulama sınırları

Masaüstü akışları macOS’ta gerçek Tk penceresinde ve çevrimdışı worker süreçleriyle
sınandı. Windows çift tık başlatıcısının hedef makinede ve canlı Jira kimlik doğrulama /
ekran akışlarının kurum Jira ortamında doğrulanması gerekir. Bu sürüm exe paketi,
parola kasası, zamanlama veya paralel test koşusu içermez.
