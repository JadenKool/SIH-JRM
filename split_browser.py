"""Keep two Chrome feed windows ready to show side by side."""

from pathlib import Path

from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.common.exceptions import WebDriverException


class SplitBrowser:
    def __init__(self):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "none"
        # Keep sign-ins between runs in a profile shared by the two feed windows.
        options.add_argument(f"--user-data-dir={Path.home() / '.doomscroller-chrome'}")
        self.driver = webdriver.Chrome(options=options)
        self.windows = [self.driver.current_window_handle]
        self.window_ids = []

    def prepare_feeds(self, urls):
        driver = self.driver
        left, top, width, height = driver.execute_script(
            "return [screen.availLeft, screen.availTop, screen.availWidth, screen.availHeight];"
        )
        half = width // 2
        for index, url in enumerate(urls):
            if index:
                driver.switch_to.new_window("window")
                self.windows.append(driver.current_window_handle)
            x = left if index == 0 else left + half
            pane_width = half if index == 0 else width - half
            driver.set_window_rect(x=x, y=top, width=pane_width, height=height)
            window_id = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})["windowId"]
            self.window_ids.append(window_id)
            driver.get(url)
        self.hide()

    def _set_window_state(self, state):
        for window_id in self.window_ids:
            self.driver.execute_cdp_cmd("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {"windowState": state},
            })

    def hide(self):
        self._set_window_state("minimized")

    def show(self):
        self._set_window_state("normal")
        self.driver.execute_cdp_cmd("Page.bringToFront", {})

    def scroll(self):
        driver = self.driver
        for window in self.windows:
            driver.switch_to.window(window)
            ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()

    def freeze_feeds(self, paused, stopping):
        frozen = []
        for window in self.windows:
            if stopping.is_set() or not paused.is_set():
                break
            try:
                self.driver.switch_to.window(window)
                frozen.append(window)
                self.driver.execute_script("""
                    window.__doomscrollerPausedMedia = [...document.querySelectorAll('video, audio')]
                        .filter(media => !media.paused && !media.ended);
                    window.__doomscrollerPausedMedia.forEach(media => media.pause());
                """)
                self.driver.execute_cdp_cmd("Page.setWebLifecycleState", {"state": "frozen"})
            except WebDriverException:
                continue
        return frozen

    def resume_feeds(self, frozen):
        for window in frozen:
            try:
                self.driver.switch_to.window(window)
                self.driver.execute_cdp_cmd("Page.setWebLifecycleState", {"state": "active"})
                self.driver.execute_script("""
                    for (const media of window.__doomscrollerPausedMedia || []) {
                        media.play().catch(() => {});
                    }
                    delete window.__doomscrollerPausedMedia;
                """)
            except WebDriverException:
                continue

    def close(self):
        self.driver.quit()
