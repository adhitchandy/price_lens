import time

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def _js_click(driver, element):
    """Click via JavaScript — bypasses overlays and visibility issues."""
    driver.execute_script("arguments[0].click();", element)


def _js_set(driver, element, value):
    """Set an input value via JS and fire an input event so Amazon's JS notices."""
    driver.execute_script("arguments[0].value = '';",          element)
    driver.execute_script("arguments[0].value = arguments[1];", element, value)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", element)


def _wait_for_real_page(driver, domain, timeout=20):
    """
    Waits for either:
      (a) The real Amazon navbar — page loaded normally, proceed
      (b) The 'Continue shopping' interstitial button — click it, then wait again

    This is the correct pattern for handling Amazon's bot-check page:
    don't look for the interstitial first; instead wait for whichever
    comes first (real page or interstitial) and react to it.
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        except WebDriverException:
            time.sleep(0.5)
            continue

        # ── Case 1: Real page loaded ──────────────────────────────────────────
        try:
            driver.find_element(By.ID, "nav-global-location-popover-link")
            return True  # Real page confirmed — proceed
        except WebDriverException:
            pass

        # ── Case 2: Interstitial detected — click through it ─────────────────
        if "continue shopping" in body_text or "click the button below" in body_text:
            for sel in ("input[type='submit']", "button[type='submit']", "button"):
                try:
                    btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    btn.click()  # native click — emulates physical mouse click
                    time.sleep(2.5)
                    break
                except (TimeoutException, WebDriverException):
                    continue

        time.sleep(0.8)

    return False  # Timed out — neither real page nor interstitial handled


def _click_confirm_close(driver):
    """
    Clicks the GLUXConfirmClose / Done button after a postcode is applied.
    Waits for it to become un-hidden first (Amazon reveals it asynchronously).
    """
    try:
        WebDriverWait(driver, 5).until(
            lambda d: "GLUX_Hidden" not in
            d.find_element(By.ID, "GLUXConfirmClose")
             .find_element(By.XPATH, "./ancestor::div[contains(@class,'GLUX')]")
             .get_attribute("class")
        )
    except (TimeoutException, WebDriverException):
        pass  # Best-effort — proceed anyway
    try:
        btn = WebDriverWait(driver, 4).until(
            EC.presence_of_element_located((By.ID, "GLUXConfirmClose")))
        _js_click(driver, btn)
        time.sleep(1.2)
    except (TimeoutException, WebDriverException):
        pass  # Popup may close automatically on some locales


# ── Domains that already show the correct local location — skip entirely ──────
SKIP_LOCATION_DOMAINS = {
    "amazon.ca",        # Balzac, Canada — already local
    "amazon.com.br",    # Brazil — already local
    "amazon.nl",        # Amsterdam — already local
    "amazon.se",        # Stockholm — already local
    "amazon.pl",        # Warsaw — already local
    "amazon.ae",        # Dubai — already local
    "amazon.sa",        # Riyadh — already local
    "amazon.com.be",    # Brussels — already local
    "amazon.eg",        # Cairo — already shows Egyptian location
}


def _set_location_standard(driver, postcode):
    """
    Standard GLUX flow used by most Amazon locales:
      type into #GLUXZipUpdateInput → Apply → Confirm/Done
    """
    zip_input = WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput")))
    driver.execute_script("arguments[0].scrollIntoView(true);", zip_input)
    time.sleep(0.4)
    _js_set(driver, zip_input, postcode)
    time.sleep(0.6)

    apply_btn = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#GLUXZipUpdate input[type='submit']")))
    _js_click(driver, apply_btn)
    time.sleep(2.0)

    # Guard against sign-in redirect (Amazon tries to save the address to an account)
    # We pass domain=None here; the caller (set_delivery_location) handles the redirect check.

    # Wait for confirmation section to appear (loses GLUX_Hidden class)
    try:
        WebDriverWait(driver, 5).until(
            lambda d: "GLUX_Hidden" not in
            d.find_element(By.ID, "GLUXZipConfirmationSection")
             .get_attribute("class"))
    except TimeoutException:
        pass

    _click_confirm_close(driver)


def _set_location_japan(driver, postcode):
    """
    Japan (amazon.co.jp) uses two separate inputs:
      #GLUXZipUpdateInput_0  — first 3 digits  (e.g. "100")
      #GLUXZipUpdateInput_1  — last  4 digits  (e.g. "0001")
    Postcode format in config: "100-0001"
    """
    # Split on hyphen; pad/trim defensively
    parts = postcode.replace(" ", "").split("-")
    part0 = parts[0][:3]  if len(parts) > 0 else ""
    part1 = parts[1][:4]  if len(parts) > 1 else ""

    inp0 = WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput_0")))
    driver.execute_script("arguments[0].scrollIntoView(true);", inp0)
    time.sleep(0.4)
    _js_set(driver, inp0, part0)

    inp1 = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput_1")))
    _js_set(driver, inp1, part1)
    time.sleep(0.6)

    apply_btn = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#GLUXZipUpdate input[type='submit']")))
    _js_click(driver, apply_btn)
    time.sleep(1.5)

    _click_confirm_close(driver)


def _set_location_australia(driver, postcode):
    """
    Australia (amazon.com.au):
      1. Type postcode into #GLUXPostalCodeWithCity_PostalCodeInput using send_keys
         (JS value injection won't trigger Amazon's React listener)
      2. Wait for the city dropdown prompt to appear, then click it to open
      3. Select first city option (#GLUXPostalCodeWithCity_DropdownList_0)
      4. Click Apply — no 'Done' button, popup closes automatically
    """
    zip_input = WebDriverWait(driver, 8).until(
        EC.element_to_be_clickable(
            (By.ID, "GLUXPostalCodeWithCity_PostalCodeInput")))
    driver.execute_script("arguments[0].scrollIntoView(true);", zip_input)
    time.sleep(0.4)
    zip_input.clear()
    zip_input.send_keys(postcode)
    time.sleep(1.5)  # wait for city dropdown prompt to become active

    # Click the dropdown prompt to open the city list
    dropdown_prompt = WebDriverWait(driver, 8).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR,
             ("#GLUXPostalCodeWithCity_CityValue, "
              "span.a-dropdown-prompt"))))
    _js_click(driver, dropdown_prompt)
    time.sleep(0.8)

    # Pick the first city in the list
    first_city = WebDriverWait(driver, 8).until(
        EC.element_to_be_clickable(
            (By.ID, "GLUXPostalCodeWithCity_DropdownList_0")))
    _js_click(driver, first_city)
    time.sleep(0.6)

    # Click Apply using the confirmed XPath — emulate a physical click
    apply_btn = WebDriverWait(driver, 6).until(
        EC.element_to_be_clickable(
            (By.XPATH, '//*[@id="GLUXPostalCodeWithCityApplyButton"]')))
    driver.execute_script("arguments[0].scrollIntoView(true);", apply_btn)
    time.sleep(0.3)
    apply_btn.click()  # native click — emulates physical mouse click
    time.sleep(2.0)

    # Amazon.com.au sometimes redirects to sign-in after setting location.
    # Navigate back — the location cookie is already set so it persists.
    _handle_signin_redirect(driver, "amazon.com.au")


def _handle_signin_redirect(driver, domain):
    """
    After setting a location, Amazon sometimes redirects to a sign-in page
    to 'save' the address. Since we have no account, we just navigate back.
    The location cookie is already written — going back preserves it.
    Returns True if a redirect was detected and handled.
    """
    try:
        current_url = driver.current_url.lower()
        if "signin" in current_url or "ap/signin" in current_url or "login" in current_url:
            driver.get(f"https://{domain}")
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.ID, "nav-global-location-popover-link")))
            time.sleep(1.0)
            return True
    except (TimeoutException, WebDriverException):
        pass
    return False
_LOCATION_HANDLERS = {
    "amazon.com":      _set_location_standard,   # same input IDs as standard
    "amazon.co.jp":    _set_location_japan,
    "amazon.com.au":   _set_location_australia,
    # All other domains use _set_location_standard (default)
}


def set_delivery_location(driver, domain, postcode, log_fn):
    """
    Entry point: loads the domain homepage, dismisses any overlay,
    then routes to the correct location-setting handler for that domain.
    Domains in SKIP_LOCATION_DOMAINS are silently skipped.
    """
    # ── Skip domains that are already showing their local location ────────────
    if domain in SKIP_LOCATION_DOMAINS:
        log_fn(f"  ⏭️ `{domain}` already shows local location — skipping")
        return True

    try:
        # ── Load homepage ─────────────────────────────────────────────────────
        driver.get(f"https://{domain}")

        # ── Wait for real page OR handle 'Continue shopping' interstitial ─────
        # _wait_for_real_page polls in a loop: if the real navbar appears it
        # proceeds immediately; if the interstitial appears it clicks through
        # and waits again. This is a proper shock absorber — no racing.
        page_ready = _wait_for_real_page(driver, domain, timeout=25)
        if not page_ready:
            raise TimeoutException(
                "Real page never loaded — possible CAPTCHA or hard block")

        # ── Click "Deliver to" trigger ────────────────────────────────────────
        # Use element_to_be_clickable (not just presence) so we wait for JS
        # event listeners to attach before clicking.
        clicked_trigger = False
        for trigger_sel in (
            "#nav-global-location-popover-link",
            "#glow-ingress-block",
            "a#nav-global-location-popover-link",
        ):
            try:
                loc_btn = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, trigger_sel)))

                # Critical: give Amazon's JS time to attach event listeners
                # AFTER the element is found but BEFORE clicking
                time.sleep(1.5)

                # Try native click first (React needs real browser events);
                # fall back to JS click if an overlay intercepts it
                try:
                    loc_btn.click()
                except WebDriverException:
                    _js_click(driver, loc_btn)

                time.sleep(2.5)  # wait for popup to animate and fully render
                clicked_trigger = True
                break
            except (TimeoutException, WebDriverException):
                continue

        if not clicked_trigger:
            raise TimeoutException("Could not find or click the location trigger button")

        # ── Route to domain-specific handler ─────────────────────────────────
        handler = _LOCATION_HANDLERS.get(domain, _set_location_standard)
        handler(driver, postcode)

        # ── Guard: if Amazon redirected to sign-in, go back ──────────────────
        # Amazon sometimes redirects after Apply to ask user to save the address.
        # The location cookie is already set — navigating back preserves it.
        if _handle_signin_redirect(driver, domain):
            log_fn(f"  🔄 Sign-in redirect detected on `{domain}` — returned to homepage")

        # ── Confirm popup is gone ─────────────────────────────────────────────
        try:
            WebDriverWait(driver, 4).until(
                EC.invisibility_of_element_located(
                    (By.ID, "nav-global-location-popover-link"
                     if False else "GLUXZipUpdateInput")))
        except TimeoutException:
            pass

        log_fn(f"  📍 Location set to **{postcode}** on `{domain}`")
        return True

    except (TimeoutException, WebDriverException) as exc:
        log_fn(
            f"  ⚠️ Could not set location on `{domain}` "
            f"({exc.__class__.__name__}) — scraping without location override")
        return False
