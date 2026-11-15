"""Place two Chrome windows side by side and send keys to their pages."""

from pathlib import Path

from selenium import webdriver
from selenium.webdriver import ActionChains, Keys


class SplitBrowser:
    def __init__(self):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "none"
        # Keep sign-ins between runs in a profile shared by the two feed windows.
        options.add_argument(f"--user-data-dir={Path.home() / '.doomscroller-chrome'}")
        self.driver = webdriver.Chrome(options=options)
        self.windows = [self.driver.current_window_handle]

    def open_feeds(self, urls):
        driver = self.driver
        open_windows = driver.window_handles
        self.windows = [window for window in self.windows if window in open_windows]
        while len(self.windows) < len(urls):
            driver.switch_to.new_window("window")
            self.windows.append(driver.current_window_handle)

        driver.switch_to.window(self.windows[0])
        left, top, width, height = driver.execute_script(
            "return [screen.availLeft, screen.availTop, screen.availWidth, screen.availHeight];"
        )
        half = width // 2
        for index, (window, url) in enumerate(zip(self.windows, urls)):
            driver.switch_to.window(window)
            x = left if index == 0 else left + half
            pane_width = half if index == 0 else width - half
            driver.set_window_rect(x=x, y=top, width=pane_width, height=height)
            driver.get(url)

    def scroll(self):
        driver = self.driver
        for window in self.windows:
            driver.switch_to.window(window)
            ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()

    def close(self):
        self.driver.quit()
