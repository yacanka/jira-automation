# Kullanım ve senaryo referansı

Windows'ta repo kökünde çalışın. `bat` blokları CMD komutlarıdır; yeni
CMD penceresinde önce `call .venv\Scripts\activate.bat` çalıştırın.
`python` blokları [README](../README.md) içindeki `main` importunu ve gizli parola
girişini yaptığınız **aynı Python konsolunda** çalıştırılır. Python konsolundan
çıkmak için `exit()` yazın; yeniden açtığınızda kimlik bilgilerini tekrar girin.
Python'a verilen `examples/yaml` gibi yollar Windows'ta da geçerlidir.

## 1. Ortamı doğrulayın

`config.example.yaml` dosyasını kopyalayın. Kaynak proje salt okunur keşif içindir;
`test_project` farklı bir proje olmalıdır. Jira yöneticisi test projesinin ilgili
issue türü, ekran, alan, workflow ve izin yapılandırmasını kaynakla eşlemelidir.
Sistem Jira yapılandırması veya proje oluşturmaz.

`main(["doctor", "--config", "config.local.yaml"])` API kimliğini, sürümü, proje erişimini,
oluşturma metadatasını, yetkileri ve tarayıcı girişini denetler. Yalnız API kontrolü
istiyorsanız argüman listesine `"--api-only"` ekleyin. CAPTCHA, MFA, SSO veya basic auth engeli varsa
kurumunuzun izin verdiği test hesabı/giriş yöntemi gerekir; sistem bunları aşmaz.

## 2. Kataloğu oluşturun

```python
main(["explore", "--config", "config.local.yaml", "--project", "DEMO"])
main(
    [
        "explore",
        "--config",
        "config.local.yaml",
        "--project",
        "AUTOTEST",
        "--output",
        "artifacts/test-catalog",
    ]
)
main(["explore", "--config", "config.local.yaml", "--api-only"])
```

Davranış testlerinde kullanılacak kimlikleri test projesi kataloğundan seçin.
Alan ID'si (`customfield_...`), issue türü ID'si ve transition ID'si farklı kavramlardır.
Bir statüye birden fazla geçiş olabilir; eylem için transition ID, assertion için
hedef status ID kullanılır. DOM locator'ı Jira alan ID'si ile aynı olmak zorunda değildir.

`samples` ayarı issue türü ID'sinden erişilebilir issue anahtarlarına eşlemedir.
Özellikle terminal statüler, özel alan bağlamları ve subtask ekranları için örnekler
verin. Otomatik keşif her türden en fazla `sample_limit` kayıt inceler. Keşif tüm
workflow grafiğini gezmek için kayıtları değiştirmez. Eksikler katalogda `gaps` olarak
bulunur. İsteklerin kullanıcı/yetki bağlamı tek yapılandırılmış test hesabıdır.

API erişimi yoksa explorer tarayıcı girişini kullanarak sınırlı keşif yapar. Bu mod
native project/type select kontrollerine ve `samples` kayıtlarına dayanır; geçiş
butonlarını çalıştırmaz. Şema, görünmeyen statüler ve validator'lar bilinmez kalır.

HTML rapor dış servis çağırmadan yerel açılır; kimlikler JSON'da da bulunur:

```bat
python -m jira_test query --catalog artifacts/test-catalog/catalog.json --issue-type 10001 --screen transition --transition 31 --field customfield_10012
```

Eski snapshot güncel Jira davranışının kanıtı değildir; yapılandırma değişince yeniden keşfedin.

## 3. YAML yazın

```yaml
id: description-edit
fixture:
  issue_type: "10001"
steps:
  - action: open
    screen: edit
  - action: fill
    field: description
    value: Örnek açıklama
  - action: submit
expect:
  - check: accepted
    value: true
  - check: persisted
    field: description
    value: Örnek açıklama
```

Sayısal kimlikler string olduğu için tırnak kullanın. Test verisindeki gerçek sayıları
ise sayı olarak yazın. YAML `safe_load` eşdeğeri yüklenir; executable expression,
Python etiketi, bilinmeyen anahtar ve duplicate key kabul edilmez.

UI beklentileri (`visible`, `editable`, `required`) için senaryonun son ekranı
açıkça açılmış olmalıdır. `submit` veya `transition` sonrasında UI kontrolü
yapılacaksa uygun ekranı tekrar açın. `accepted` bir gönderim/geçiş gerektirir;
`error_contains` boş olmayan metin olmalıdır. Bu hatalar çevrimdışı doğrulamada
yakalanır. `persisted` kontrolünde `value: null`, yalnız API cevabında bulunan ve
değeri gerçekten null olan alan için geçer; eksik alan `blocked` olarak raporlanır.

### Fixture

| Anahtar | Anlamı |
|---|---|
| `issue_type` | Test projesindeki issue türü ID'si; zorunlu |
| `mode: new` | Varsayılan; API ile bağımsız kayıt hazırlar |
| `mode: none` | Önceden issue oluşturmaz; katalog veya create ekranı testi |
| `fields` | API biçiminde başlangıç alanları; summary için varsayılan üretilir |
| `parent` | `issue_type` ve isteğe bağlı `fields` ile bu çalıştırmada parent hazırlar |
| `path` | Başlangıç statüsüne gitmek için sıralı `{id, fields, status}` geçişleri |
| `catalog` | Katalog assertion'ları için JSON dosyası; çalışma dizinine göre çözülür |

`default_fields` tüm fixture'lara uygulanır. API değerleri ile UI değerlerinin biçimi
farklı olabilir: API seçimleri `{id: "20001"}`; UI autocomplete ise görünen etiketi
kullanır. Create ekranında default_fields UI üzerinden de doldurulur; bu alanlar için
uygun komponent ve locator gereklidir. Project, parent ve issue türü motor tarafından
kontrol edilir; senaryo adımlarıyla değiştirilemez.

Örneğin başlangıç statüsüne hazırlık:

```yaml
fixture:
  issue_type: "10001"
  path:
    - id: "21"
      fields:
        customfield_10012: Hazır
      status: "10002"
```

API üzerinden hazırlık yapılan geçiş, test edilen geçiş değildir. Test edilen kullanıcı
adımı Playwright üzerinden yürütülmelidir.

### İşlemler

| `action` | Gerekli değerler | Davranış |
|---|---|---|
| `open` | `screen` | `create`, `view`, `edit`, `transition`; geçiş için `transition` ID |
| `fill` | `field`, `value` | Açık formda komponent üzerinden doldurur |
| `clear` | `field` | Alanı komponent türüne uygun temizler |
| `submit` | — | Açık formu bir kere gönderir; açık validation veya başarı bekler |
| `transition` | `id`, isteğe bağlı `fields` | Geçişi açar, alanları doldurur ve gönderir |

Form açmadan fill/clear/submit kullanılamaz. Bir submit sonrasında yeni işlem için
form yeniden açılmalıdır. Screenless geçişler UI düğmesiyle doğrudan çalışır; bunlara
form alanı verilmemelidir. Explorer screenless geçişleri asla çalıştırmaz.

### Assertion'lar

| `check` | Kontrol edilen bilgi |
|---|---|
| `visible` / `editable` | Alanın açık ekrandaki gözlenen durumu |
| `required` | Açık ekrandaki zorunluluk işareti; gerçek validator kanıtı değildir |
| `accepted` | Son submit sonucu; false için `error_contains`, isteğe bağlı `field` gerekir |
| `persisted` | REST ile kalıcı alan değeri; `{id: ...}` mapping'i belirtilen anahtarları karşılaştırır |
| `status` | REST üzerinden status ID |
| `transition_available` | Mevcut issue için kullanıcıya açık transition ID |
| `catalog_exists` | Belirtilen bağlamda alan gözlemi; API varlık, UI görünürlük bilgisi |
| `catalog_required` | Seçilen API/UI kaynağında zorunluluk bilgisi |
| `catalog_options` | API seçeneklerinde `contains` ile aranan değer veya mapping |

Katalog assertion'ları `field`, `screen`, isteğe bağlı `status`/`transition` filtrelerini
kullanır. `catalog_required` ve `catalog_options` için `source` zorunludur. Birden çok
gözlem varsa hepsi beklentiyi sağlamalıdır. Hiç gözlem yoksa `blocked` sonucu çıkar;
keşfedilmemiş alan hakkında `false` sonucu üretilmez. `catalog_exists: false` için
ilgili bağlamda açık bir UI `visible: false` gözlemi gerekir.

Negatif kaydetme testleri hata mesajını ve mevcut kaydın değişmediğini kontrol eder.
Negatif create testi çalıştırma kimliğiyle beklenmedik yeni issue oluşmadığını REST
aramasıyla kontrol eder; Jira arama indeksi gecikmesi bu kontrolün sınırıdır. Timeout,
bağlantı problemi veya unsupported widget iş kuralı reddi olarak kabul edilmez.
API mapping assertion'ları ek anahtarları önemsemez; listeler sıra ve uzunluğu korunarak aynı mapping projeksiyonuyla
karşılaştırılır. Rich text, tarih ve kullanıcı alanlarının API biçimini kataloğun şeması
ve Jira dokümantasyonu üzerinden uyarlayın.

## 4. Çalıştırma ve sonuçlar

```python
main(["validate", "--suite", "my-scenarios"])
main(
    [
        "run",
        "--suite",
        "my-scenarios",
        "--config",
        "config.local.yaml",
        "--test-project",
        "AUTOTEST",
        "--catalog",
        "artifacts/test-catalog/catalog.json",
    ]
)
```

Exit code 0 tüm toplanan testlerin geçtiğini gösterir. Engellenen YAML senaryoları pytest'te
başarısız raporlanır; sessiz skip yapılmaz. JSON sonuçta `blocked` ayrı belirtilir.
`artifacts/junit.xml` CI sonucu; `artifacts/test-results.json` oluşturulan kayıtların
listesi ve YAML test sonuçlarıdır. Ayrı çalıştırmalar dosyayı yeniler; geçmişi korumak
için her koşuya farklı `artifact_dir` ve `--junit` verin.

Ekran görüntüleri varsayılan kapalıdır. `screenshots: true` ile açılırsa hata anındaki
ekranlar kullanıcı/issue verisi içerebilir; artifact erişimini kurum politikanıza göre
sınırlayın. Credential, cookie, API response body ve ham issue verisi rapora yazılmaz.
UI locator sorunları `locators` ile, eklenti widget'ları registry adaptörüyle çözülür.
Üçüncü taraf widget'lara otomatik olarak genel metin komponenti uygulanmaz.

## Masaüstünden kullanım

Aynı işlemler `python -m jira_test gui` ile açılan Tkinter arayüzünden de yapılabilir.
[Görsel test tasarımcısı ve koşu geçmişi rehberi](gui.md).
