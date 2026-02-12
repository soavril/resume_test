"""Auto-fill web forms using Playwright."""

from __future__ import annotations


async def autofill_form(url: str, answers: list[dict]) -> int:
    """Open the URL in a visible browser, fill textarea fields, and wait.

    The browser stays open until the user closes it manually.
    Returns the number of fields filled.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Collect all textareas with their labels
        textarea_info = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('textarea').forEach((ta, idx) => {
                let label = '';

                // aria-label
                if (ta.getAttribute('aria-label')) {
                    label = ta.getAttribute('aria-label');
                }

                // label[for]
                const id = ta.id;
                if (id && !label) {
                    const labelEl = document.querySelector(`label[for="${id}"]`);
                    if (labelEl) label = labelEl.textContent.trim();
                }

                // Walk up DOM
                if (!label) {
                    let el = ta.parentElement;
                    for (let i = 0; i < 5 && el; i++) {
                        const prev = el.previousElementSibling;
                        if (prev) {
                            const text = prev.textContent.trim();
                            if (text.length > 3 && text.length < 500) {
                                label = text;
                                break;
                            }
                        }
                        el = el.parentElement;
                    }
                }

                if (!label) label = ta.placeholder || '';

                results.push({idx: idx, label: label});
            });
            return results;
        }""")

        # Match answers to textareas by label similarity
        textareas = await page.query_selector_all("textarea")
        filled = 0

        for ta_info in textarea_info:
            ta_label = ta_info["label"]
            ta_idx = ta_info["idx"]

            if ta_idx >= len(textareas):
                continue

            # Skip script content, generic labels
            if any(skip in ta_label.lower() for skip in ["window.", "function ", "datalayer"]):
                continue

            # Find matching answer
            matched_answer = _find_matching_answer(ta_label, answers)
            if matched_answer:
                ta = textareas[ta_idx]
                await ta.click()
                await ta.fill(matched_answer["answer"])
                filled += 1

        # Wait until user closes the browser window
        await browser.wait_for_event("disconnected")

    return filled


def _find_matching_answer(label: str, answers: list[dict]) -> dict | None:
    """Find the best matching answer for a textarea label."""
    label_lower = label.lower().strip()

    # Direct substring match
    for ans in answers:
        q = ans["question"].lower().strip()
        if q in label_lower or label_lower in q:
            return ans

    # Keyword overlap match
    best_match = None
    best_score = 0
    for ans in answers:
        q_words = set(ans["question"].lower().split())
        l_words = set(label_lower.split())
        overlap = len(q_words & l_words)
        if overlap > best_score and overlap >= 2:
            best_score = overlap
            best_match = ans

    return best_match
