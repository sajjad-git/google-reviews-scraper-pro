"""
In-page batch extraction of review cards.

The original scroll loop touched every card through WebDriver: one HTTP
round trip to chromedriver per card just to read its id, then 25-40 more
per fresh card inside RawReview.from_card(). On a large place that made
each scroll iteration cost seconds and grow with the review count.

This module does the same work with two execute_script calls per
iteration, regardless of how many cards are on the page:

  1. EXPAND_JS   - click every "More" button on cards not yet scraped,
                   so the full text is present in the DOM.
  2. EXTRACT_JS  - read every not-yet-scraped card into a plain object,
                   mark it data-scraped="1", prune already-scraped cards
                   from the DOM (keeping the last N so Google's infinite
                   scroll still has an anchor), and return the batch.

Selectors mirror RawReview.from_card() exactly; Python-side parsing
(rating number, date -> ISO, language, likes, sub-ratings) is done by
RawReview.from_dict() so behaviour stays identical.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from selenium.webdriver import Chrome
from selenium.webdriver.remote.webelement import WebElement

# Keep in sync with RawReview.* selector tuples in models.py.
_MORE_BTN = (
    "button.kyuRq",
    'button[jsaction*="expandReview"]',
    'button[aria-expanded="false"][jsaction*="review" i]',
)
_LIKE_BTN = 'button[jsaction*="toggleThumbsUp" i]'
_PHOTO_BTN = (
    "button.Tya61d",
    'button[aria-label*="Photo" i][style*="url"]',
    "button[data-photo-index]",
)
_OWNER_RESP = ("div.CDe7pd", 'div[class*="owner" i]')
_OWNER_DATE = ("span.DZSIDd", 'span[class*="ownerdate" i]')
_OWNER_TEXT = ("div.wiI7pd", 'div[class*="ownerresp" i]')
_TEXT = ('span[jsname="bN97Pc"]', 'span[jsname="fbQN7e"]', "div.MyEned span.wiI7pd")
_RATING = ('span[role="img"][aria-label]', 'span[class*="kvMYJc" i]')
_DATE = ('span[class*="rsqaWe"]', 'span[class*="xRkPPb" i]')
_SUB_RATING = ("div.PBK6be", 'div[class*="rating" i][aria-label*="/5" i]')


def _js_list(sels: Tuple[str, ...]) -> str:
    return "[" + ",".join(repr(s) for s in sels) + "]"


# arguments[0] = pane WebElement
# returns: number of "More" buttons clicked
EXPAND_JS = f"""
const pane = arguments[0];
const MORE = {_js_list(_MORE_BTN)};
let clicked = 0;
for (const card of pane.querySelectorAll('div[data-review-id]:not([data-scraped])')) {{
  for (const sel of MORE) {{
    const btns = card.querySelectorAll(sel);
    if (!btns.length) continue;
    for (const b of btns) {{ try {{ b.click(); clicked++; }} catch (e) {{}} }}
    break;
  }}
}}
return clicked;
"""

# arguments[0] = pane WebElement, arguments[1] = keepLast (0 disables pruning)
# returns: {{dom_cards, pruned, cards:[...]}}
EXTRACT_JS = f"""
const pane = arguments[0];
const keepLast = arguments[1] | 0;

const TEXT = {_js_list(_TEXT)}, RATING = {_js_list(_RATING)}, DATE = {_js_list(_DATE)};
const PHOTO = {_js_list(_PHOTO_BTN)}, OWNER = {_js_list(_OWNER_RESP)};
const ODATE = {_js_list(_OWNER_DATE)}, OTEXT = {_js_list(_OWNER_TEXT)};
const SUB = {_js_list(_SUB_RATING)};
const LIKE = {_LIKE_BTN!r};

const txt = el => el ? (el.innerText || el.textContent || '').trim() : '';
const firstEl = (root, sels) => {{
  for (const s of sels) {{ const el = root.querySelector(s); if (el) return el; }}
  return null;
}};
const firstText = (root, sels) => {{
  for (const s of sels) {{ const t = txt(root.querySelector(s)); if (t) return t; }}
  return '';
}};
const allOfFirst = (root, sels) => {{
  for (const s of sels) {{ const els = root.querySelectorAll(s); if (els.length) return Array.from(els); }}
  return [];
}};

const allCards = Array.from(pane.querySelectorAll('div[data-review-id]'));
const out = [];

for (const card of allCards) {{
  if (card.hasAttribute('data-scraped')) continue;
  card.setAttribute('data-scraped', '1');
  const rid = card.getAttribute('data-review-id') || '';
  if (!rid) continue;

  // Same order/logic as RawReview.from_card: the Python side picks the
  // first label that parses to a rating in (0, 5].
  const ratingLabels = [];
  for (const s of RATING) {{
    const el = card.querySelector(s);
    const l = el ? (el.getAttribute('aria-label') || '') : '';
    ratingLabels.push(l);
  }}

  const likeBtn = card.querySelector(LIKE);
  const likesText = likeBtn ? (txt(likeBtn) || likeBtn.getAttribute('aria-label') || '') : '';

  const photoStyles = allOfFirst(card, PHOTO).map(b => b.getAttribute('style') || '');

  let ownerDate = '', ownerText = '';
  const box = firstEl(card, OWNER);
  if (box) {{ ownerDate = firstText(box, ODATE); ownerText = firstText(box, OTEXT); }}

  const subLabels = allOfFirst(card, SUB)
    .map(b => (b.getAttribute('aria-label') || txt(b) || '').trim())
    .filter(Boolean);

  const profBtn = card.querySelector('button[data-review-id]');
  const avatarImg = card.querySelector('button[data-review-id] img');

  out.push({{
    id: rid,
    author: txt(card.querySelector('div[class*="d4r55"]')),
    profile: profBtn ? (profBtn.getAttribute('data-href') || '') : '',
    avatar: avatarImg ? (avatarImg.getAttribute('src') || '') : '',
    rating_labels: ratingLabels,
    date: firstText(card, DATE),
    text: firstText(card, TEXT),
    likes_text: likesText,
    photo_styles: photoStyles,
    owner_date: ownerDate,
    owner_text: ownerText,
    sub_rating_labels: subLabels,
  }});
}}

// Prune: drop already-scraped cards except the last keepLast, so the DOM
// (and the renderer's memory + layout cost) stays flat for the whole scrape.
let pruned = 0;
if (keepLast > 0) {{
  const scraped = allCards.filter(c => c.hasAttribute('data-scraped'));
  const excess = scraped.length - keepLast;
  for (let i = 0; i < excess; i++) {{ try {{ scraped[i].remove(); pruned++; }} catch (e) {{}} }}
}}

return {{ dom_cards: allCards.length, pruned: pruned, cards: out }};
"""


def extract_batch(
    driver: Chrome,
    pane: WebElement,
    keep_last: int = 30,
    expand_wait: float = 0.3,
) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Expand + extract every not-yet-scraped card under `pane`.

    Returns (dom_cards_before_prune, pruned_count, cards) where each card is
    a plain dict suitable for RawReview.from_dict(). Raises whatever
    execute_script raises (StaleElementReferenceException if the pane went
    away, WebDriverException if the session died) so the caller's existing
    handlers keep working.
    """
    import time

    clicked = driver.execute_script(EXPAND_JS, pane) or 0
    if clicked and expand_wait > 0:
        time.sleep(expand_wait)  # let Google swap in the full text
    result = driver.execute_script(EXTRACT_JS, pane, int(keep_last)) or {}
    return (
        int(result.get("dom_cards", 0)),
        int(result.get("pruned", 0)),
        list(result.get("cards", []) or []),
    )