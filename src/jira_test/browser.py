"""WebDriver lifecycle and Jira username/password login with explicit waits."""

from urllib.parse import urlsplit

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .components import LocatorMap
from .config import Config
from .errors import ConfigurationError, WriteBoundaryError


class Browser:
    def __init__(self, config: Config, driver: WebDriver | None = None):
        self.config = config
        self.driver = driver
        self.locators = LocatorMap(config.locators)

    def start(self) -> WebDriver:
        if self.driver is not None:
            return self.driver
        if self.config.browser == "chrome":
            options = webdriver.ChromeOptions()
            if self.config.headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,1000")
            self.driver = webdriver.Chrome(
                options=options, service=ChromeService(executable_path=self.config.driver_path)
            )
        else:
            firefox_options = webdriver.FirefoxOptions()
            if self.config.headless:
                firefox_options.add_argument("-headless")
            self.driver = webdriver.Firefox(
                options=firefox_options,
                service=FirefoxService(executable_path=self.config.driver_path),
            )
        self.driver.implicitly_wait(0)
        self.driver.set_page_load_timeout(self.config.timeout)
        return self.driver

    def login(self) -> WebDriver:
        self.config.require_credentials()
        driver = self.start()
        driver.get(self.config.base_url + "/login.jsp")
        self.assert_origin()
        wait = WebDriverWait(driver, self.config.timeout)
        username = self.locators.get("login.username", "#login-form-username")
        password = self.locators.get("login.password", "#login-form-password")
        submit = self.locators.get("login.submit", "#login-form-submit")
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, username))).send_keys(
            self.config.username
        )
        driver.find_element(By.CSS_SELECTOR, password).send_keys(self.config.password)
        driver.find_element(By.CSS_SELECTOR, submit).click()
        user_menu = self.locators.get("login.success", "#header-details-user-fullname")
        user = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, user_menu)))
        self.assert_origin()
        actual = user.get_attribute("data-username")
        if actual and actual.lower() != self.config.username.lower():
            raise ConfigurationError("Browser session is authenticated as another Jira user")
        return driver

    def assert_origin(self) -> None:
        if self.driver is None:
            raise ConfigurationError("Browser not started")
        expected = urlsplit(self.config.base_url)
        actual = urlsplit(self.driver.current_url)
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise WriteBoundaryError("Browser left the configured Jira origin")

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
