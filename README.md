# Jira test otomasyonu

Jira Data Center projelerini keşfeden ve kullanıcı davranışlarını Selenium ile
sınayan modüler Python sistemi. Yeni testler YAML ile yazılır; özel ihtiyaçlar
aynı komponentleri kullanan pytest testleriyle genişletilir.

## Kurulum

Windows'ta otomatik örnek test için repo kökündeki `run-demo.bat` dosyasını
CMD'den çalıştırabilirsiniz. Ayrıntılar aşağıdaki **Otomatik Windows demo testi**
bölümündedir.

Python 3.11+ ve Chrome, Firefox veya Microsoft Edge gerekir. Python kurulu değilse
[Windows için Python](https://www.python.org/downloads/windows/) yükleyin ve
kurulumdan sonra yeni bir **CMD (Komut İstemi)** açın.

Repo klasörünün bulunduğu yolu kendi bilgisayarınıza göre değiştirin.
[`cd /d`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cd)
başka sürücüdeki klasöre de geçer; boşluk içeren yolları çift tırnakla yazın:

```bat
cd /d "C:\Projects\jira-automation"
python --version
```

Python sürümü en az 3.11 olmalıdır. `python` bulunamıyor veya Microsoft Store
açılıyorsa `py --version` deneyin. `py` uygun sürümü gösteriyorsa yalnız ortam
oluşturma adımında `py -m venv .venv` kullanın. İkisi de çalışmıyorsa Python
kurulumunu ve PATH/uygulama yürütme diğer adlarını kontrol edin.
Python komutları ve Windows kurulumu için
[resmî Python belgelerine](https://docs.python.org/3/using/windows.html) bakabilirsiniz.

Repo kökünde (`pyproject.toml` dosyasının bulunduğu klasör) kurulumu yapın:

```bat
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
if not exist config.local.yaml copy config.example.yaml config.local.yaml
notepad config.local.yaml
```

PowerShell veya `.ps1` dosyası gerekmez. Aktivasyon kullanmadan da komutlardaki
`python` yerine `.venv\Scripts\python.exe` yazabilirsiniz. Aşağıdaki örnekler
sanal ortamın Python'unu kullandığınızı varsayar. Yeni CMD penceresinde önce
repo klasörüne geçin, sonra `call .venv\Scripts\activate.bat` çalıştırın.
macOS/Linux'tan kopyalanmış `.venv` Windows'ta kullanılmaz; Windows ortamını
`python -m venv .venv` ile oluşturun.

`config.local.yaml` içine Jira'nın HTTPS adresini, kaynak ve ayrı test projesinin
anahtarlarını yazın. Örnek `DEMO` ve `AUTOTEST` değerlerini kendi projelerinizle
değiştirin. Test projesi önceden oluşturulmuş ve gereken Jira yapılandırmasına
sahip olmalıdır; araç proje oluşturmaz. Kopyalama komutu mevcut config'i korur.

Önce aşağıdaki **Jira bağlantısı olmadan deneyin** bölümünü çalıştırabilirsiniz;
bu aşama hesap, Jira bağlantısı veya tarayıcı gerektirmez.

Kimlik bilgilerini dosyaya veya komut geçmişine yazmadan kullanmak için CMD'de
`python` çalıştırarak Python konsolunu açın. `>>>` istemini gördükten sonra
aşağıdaki Python kodunu **satır satır** girin. Kullanıcı adı ve parola sorularını
yanıtladıktan sonra sonraki satıra geçin; `>>>` karakterlerini yazmayın:

```python
import getpass
import os
from jira_test.cli import main

os.environ["JIRA_USERNAME"] = input("Jira kullanıcı adı: ")
os.environ["JIRA_PASSWORD"] = getpass.getpass("Jira parolası: ")
```

Parola giriş sırasında görünmez. Kimlik bilgileri yalnız bu Python süreci ve
başlattığı test süreçlerinde geçerlidir; konsoldan çıkınca CMD'ye aktarılmaz.
Canlı komutları aşağıdaki `main([...])` örnekleriyle **aynı Python konsolunda**
çalıştırın. `main` dönüş değeri 0 başarı, diğer değerler hata anlamına gelir.
CI'da `JIRA_USERNAME` ve `JIRA_PASSWORD` değişkenlerini secret store'dan sağlayın.
Selenium Manager gerekirse sürücü indirir; internetsiz ortamda uyumlu sürücüyü
`driver_path` ile belirtin.
Kurum CA sertifikası REST için `verify_tls` üzerinden, tarayıcı için işletim
sistemi/tarayıcı güven deposundan tanımlanır; TLS kontrolü kapatılamaz.

Microsoft Edge kullanmak için `config.local.yaml` içinde `browser: edge` ayarlayın.
Görünür tarayıcı için `headless: false`, arka planda çalıştırmak için `headless: true`
kullanın. Edge sürücüsü gerektiğinde Selenium Manager tarafından indirilir;
internetsiz Windows ortamında uyumlu sürücünün yolunu
`driver_path: 'C:/Tools/msedgedriver.exe'` biçiminde belirtin. Yol, indirilip
çıkarılmış gerçek `.exe` dosyasını göstermeli; Edge ile sürücünün ana sürümleri
eşleşmelidir.

Windows yollarını YAML'da tek tırnak ve `/` ile yazabilirsiniz:

```yaml
browser: edge
headless: false
# Yalnız elle sürücü sağlıyorsanız:
# driver_path: 'C:/Tools/msedgedriver.exe'
# Yalnız kurumunuzun CA dosyası gerekiyorsa:
# verify_tls: 'C:/Certificates/company-ca.pem'
```

Python/YAML içindeki bu yollar Windows'ta geçerlidir. Python metinlerinde
`"C:\\Tools\\msedgedriver.exe"` veya `r"C:\Tools\msedgedriver.exe"` de kullanılabilir;
kaçış karakterleri nedeniyle düz `"C:\Tools\..."` biçiminden kaçının.

## Hızlı başlangıç

Kimlik bilgilerini girdiğiniz Python konsolunda:

```python
main(["doctor", "--config", "config.local.yaml", "--api-only"])
main(["doctor", "--config", "config.local.yaml"])
main(["explore", "--config", "config.local.yaml", "--project", "DEMO"])
main(["query", "--catalog", "artifacts/explorer/catalog.json", "--field", "summary", "--screen", "create"])
```

`artifacts/explorer/catalog.html` dosyasını tarayıcıda açın. Alan, ekran, issue türü
ve statüye göre filtreleyin; YAML düğmesi katalog assertion taslağı indirir.
API ve UI gözlemleri farklı satırlardadır. `unknown` gözlemlenemeyen bağlamdır.
Explorer kayıt oluşturmaz, kaydetmez veya workflow geçişi gerçekleştirmez.

Python konsolundan raporu açmak için:

```python
os.startfile(os.path.abspath("artifacts/explorer/catalog.html"))
```

Davranış testlerindeki kimlikleri bulmak için ayrı test projesini de keşfedin:

```python
main(["explore", "--config", "config.local.yaml", "--project", "AUTOTEST", "--output", "artifacts/test-catalog"])
```

Örnekleri önce kendi çalışma dizininize kopyalayın ve kimlikleri uyarlayın:

```python
import shutil
shutil.copytree("examples/yaml", "my-scenarios")
```

`my-scenarios` yeni bir klasör olmalıdır. Dosyalardaki kimlikleri kendi Jira
ortamınıza uyarladıktan sonra aynı Python konsolunda:

```python
main(["validate", "--suite", "my-scenarios"])
main(["run", "--suite", "my-scenarios/09_edit_text.yaml", "--config", "config.local.yaml", "--test-project", "AUTOTEST"])
```

Bir klasördeki tüm senaryoları çalıştırmak için `--suite my-scenarios` kullanın.
Her senaryo bağımsız fixture kullanır. Gerçek veri setini uyarlamadan 20 örneği
birden çalıştırmayın: bazı örnekler özel workflow/validator önkoşulları gerektirir.
Test kayıtları otomatik silinmez; çalıştırma kimliği summary önekinde ve
`artifacts/test-results.json` dosyasında bulunur.

## Jira bağlantısı olmadan deneyin

Bu komutları CMD'de çalıştırın. Python konsolundaysanız önce `exit()` yazın.

```bat
python -m jira_test validate --suite examples/yaml
python -m jira_test query --catalog examples/demo-catalog.json --field summary --source api
python -m jira_test run --suite examples/yaml/05_required_metadata.yaml --catalog examples/demo-catalog.json
```

İlk komut `Validated 20 scenario(s)` yazmalı; son komutta bir test geçmelidir.
Demo katalog sentetiktir; canlı Jira hakkında kanıt oluşturmaz.

## Otomatik Windows demo testi

Python 3.11+ kurulu olmalıdır. Repo klasöründe CMD açın ve çalıştırın:

```bat
run-demo.bat
```

Başka bir klasörden çalıştırıyorsanız tam yolu çift tırnakla yazın:

```bat
"C:\Projects\jira-automation\run-demo.bat"
```

Başka bir BAT dosyasından çağırmak için `call run-demo.bat` kullanın.
İlk kurulumda paketleri indirmek için internet veya erişilebilir paket deposu
gerekir. Demo `.venv-demo` adında ayrı bir sanal ortam oluşturur; sonraki
çalıştırmalarda aynı ortamı kullanıp bağımlılık kurulumunu yeniden kontrol eder.
Mevcut `.venv` ve `config.local.yaml` dosyasını değiştirmez.

Sırasıyla Python kontrolü, sanal ortam hazırlığı, paket kurulumu, yerel testler,
20 örnek YAML'ın doğrulaması, demo katalog sorgusu ve bir katalog testi çalışır.
Bu örnek Jira hesabı veya tarayıcı gerektirmez; canlı Jira/Edge uyumluluğunu
doğrulamaz ve Jira kaydı oluşturmaz.

Her koşu `artifacts/windows-demo-...` altında ayrı raporlar üretir:

- `unit-tests.xml`: yerel test sonuçları.
- `catalog-query.json`: sentetik katalog sorgusunun sonucu.
- `demo-junit.xml`: örnek katalog testinin sonucu.
- `artifacts/test-results.json`: o koşunun demo testine ait JSON sonuç.

Bir adım başarısızsa dosya sonraki adımları çalıştırmadan durur ve sıfırdan farklı
hata kodu döndürür. Tüm adımlar başarılıysa `SUCCESS` yazar ve kod 0 döndürür.
CMD'de bitiş kodunu görmek için hemen ardından `echo %ERRORLEVEL%` çalıştırın.
Dosyayı çift tıklamak yerine CMD'den çalıştırın; böylece sonuç ekranı açık kalır.

## Belgeler ve örnekler

- [Kullanım ve senaryo referansı](docs/usage.md)
- [20 YAML örneğinin önkoşulları ve beklenen sonuçları](examples/README.md)
- [Komponent geliştirme ve mimari](docs/architecture.md)
- [4 Python örneği](examples/python/)
- [Yerel doğrulama kaydı](docs/implementation.md)

## Doğrulama

CMD'de:

```bat
python -m pytest
python -m ruff check src tests examples/python
python -m ruff format --check src tests examples/python
python -m mypy src/jira_test
python -m pip install "setuptools>=75"
python -m build --no-isolation
```

Canlı Jira testleri yerel birim testlerine dahil değildir. Canlı bağlantı kurmadan
örneklerin koleksiyonunu kontrol etmek için CMD'de:

```bat
python -m pytest examples/python --jira-config config.local.yaml --collect-only
python -m pytest examples/yaml --jira-suite examples/yaml --jira-config config.local.yaml --collect-only
```

Canlı Python örneklerini kimlik bilgilerini girdiğiniz Python konsolundan
çalıştırmak için:

```python
import subprocess
import sys
subprocess.call([sys.executable, "-m", "pytest", "examples/python", "--jira-config", "config.local.yaml"])
```

CI ortamında kimlik bilgileri sürece sağlanmışsa `python -m jira_test ...` ve
`python -m pytest ...` komutları doğrudan kullanılabilir. Yerelde Python konsolunda
girdiğiniz kimlik bilgileri için aynı konsoldaki `main([...])` veya yukarıdaki
`subprocess.call(...)` çağrılarını kullanın.

## Sınırlar

İlk sürüm modern Data Center REST v2 oluşturma metadatası uçlarını kullanır
(Jira 8.4+). Sürümünüze veya temanıza göre locator override gerekebilir. SSO/MFA
ve CAPTCHA otomasyonu desteklenmez; kurumsal politika REST basic authentication'ı
engellerse explorer sınırlı tarayıcı keşfine geçer, davranış testleri engellenir.

Standart Jira alan komponentleri hazırdır. ScriptRunner veya başka eklentilerin
özel widget'ları için adaptör gerekir. Dinamik zorunluluklar ve validator'lar
salt metadata ile kanıtlanmaz; koşulları içeren canlı test gerekir. Keşif,
örnek issue'ların ve kullanıcı yetkilerinin erişebildiği bağlamlarla sınırlıdır.
Test projesi sonuçları, kaynak projenin alan/ekran/workflow/izin yapılandırmaları
eşleştiği ölçüde kaynak projeyi temsil eder.
