"""
오늘의 브리핑을 정적 HTML 페이지로 렌더링하는 모듈

카카오톡 메시지의 구조화된 link 필드는 사전 등록된 도메인만 허용하므로,
매일 바뀌는 언론사 링크를 직접 담을 수 없다. 대신 이 페이지 하나를
GitHub Pages로 배포해 카카오 메시지에는 이 페이지 링크만 담고,
실제 기사 링크는 이 페이지의 일반 <a> 태그로 제공한다.

기사 카드를 클릭하면 페이지 이동 없이 인앱 모달로 확장된 요약을 보여주고,
모달의 "원문 전체 보기" 버튼을 눌러야 언론사 사이트로 이동한다. JS가 꺼져 있어도
카드 자체가 실제 <a href> 링크라 원문으로는 정상 이동한다(점진적 향상).
"""
import json
from html import escape
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from ecos_client import EcosSnapshot, Indicator
from formatter import KST, CategoryBriefing
from news_service import Article

# 코스피/코스닥/환율 변동률이 이 값(%) 이상이면 강조 표시합니다.
_ECOS_EMPHASIZE_THRESHOLD = 1.0

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #f2f1ec;
    --card-bg: #ffffff;
    --text: #17171a;
    --muted: #6f6f76;
    --font-serif: Georgia, "Noto Serif KR", "Nanum Myeongjo", serif;
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 0 16px 64px;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-sans);
  }}
  .wrap {{ max-width: 1200px; margin: 0 auto; }}

  .masthead {{
    text-align: center;
    padding: 40px 0 20px;
  }}
  .masthead h1 {{
    font-family: var(--font-serif);
    font-size: 42px;
    font-weight: 700;
    margin: 0 0 14px;
    letter-spacing: -0.02em;
  }}
  .masthead .rule {{
    border: none;
    border-top: 3px double var(--text);
    max-width: 640px;
    margin: 0 auto 14px;
  }}
  .masthead .meta {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .masthead .date {{ font-family: var(--font-mono); color: var(--muted); font-size: 13px; }}
  .masthead .badge {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: #fff;
    background: #17171a;
    padding: 3px 10px;
    border-radius: 999px;
  }}

  .cat-nav {{
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 18px 0 26px;
    -webkit-overflow-scrolling: touch;
  }}
  .cat-nav a {{
    flex: none;
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 13px;
    text-decoration: none;
    color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, white);
    padding: 7px 14px;
    border-radius: 999px;
    white-space: nowrap;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 24px;
  }}

  .column h2 {{
    font-family: var(--font-serif);
    font-size: 20px;
    margin: 0 0 16px;
    padding-bottom: 10px;
    border-bottom: 3px solid var(--accent);
    color: var(--accent);
    scroll-margin-top: 16px;
  }}

  .card {{
    display: block;
    color: inherit;
    text-decoration: none;
    background: var(--card-bg);
    border-radius: 14px;
    overflow: hidden;
    margin-bottom: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.12); }}
  .card.headline {{ box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}

  .thumb {{ aspect-ratio: 16 / 9; width: 100%; overflow: hidden; background: var(--accent); }}
  .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .thumb-placeholder {{
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    font-size: 40px;
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 60%, black));
  }}

  .card-body {{ padding: 14px 16px; border-left: 4px solid var(--accent); }}
  .card.headline .card-body {{
    border-left-width: 6px;
    background: color-mix(in srgb, var(--accent) 7%, white);
  }}

  .badge-headline, .badge-source {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 4px;
    margin-bottom: 8px;
    letter-spacing: 0.02em;
  }}
  .badge-headline {{ font-weight: 700; color: #fff; background: var(--accent); }}
  .badge-source {{ color: var(--muted); background: rgba(0,0,0,0.05); }}

  .card .title {{
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 15px;
    line-height: 1.4;
    margin: 0 0 8px;
  }}
  .card.headline .title {{ font-family: var(--font-serif); font-weight: 700; font-size: 19px; }}

  .card .description {{
    margin: 0 0 10px;
    color: #444;
    font-size: 13px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .card .source-line {{ font-family: var(--font-mono); font-size: 11px; color: var(--muted); }}

  .empty {{ color: var(--muted); font-size: 13px; }}

  .stat-block {{
    background: var(--card-bg);
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .stat-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 5px 0;
    border-bottom: 1px solid #eee;
  }}
  .stat-row:last-of-type {{ border-bottom: none; }}
  .stat-row.emphasize {{
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border-radius: 6px;
    padding: 5px 6px;
    font-weight: 700;
  }}
  .stat-label {{ font-family: var(--font-sans); font-size: 12.5px; color: #444; }}
  .stat-value {{ font-family: var(--font-mono); font-size: 13.5px; margin-left: auto; margin-right: 8px; }}
  .stat-change {{ font-family: var(--font-mono); font-size: 12px; }}
  .stat-change.up {{ color: #d92626; }}
  .stat-change.down {{ color: #2563d9; }}
  .stat-source {{ font-family: var(--font-mono); font-size: 10px; color: var(--muted); margin-top: 8px; }}

  footer {{ margin-top: 40px; color: #a1a1a6; font-size: 12px; text-align: center; font-family: var(--font-mono); }}

  #modal-overlay {{
    position: fixed; inset: 0;
    background: rgba(10,10,12,0.6);
    display: none;
    align-items: center; justify-content: center;
    padding: 20px;
    z-index: 100;
  }}
  #modal-overlay.open {{ display: flex; }}
  .modal {{
    background: var(--card-bg);
    max-width: 640px; width: 100%;
    max-height: 88vh;
    overflow-y: auto;
    border-radius: 16px;
    position: relative;
  }}
  .modal-close {{
    position: absolute; top: 12px; right: 12px;
    width: 32px; height: 32px;
    border-radius: 50%;
    background: rgba(0,0,0,0.55);
    color: #fff;
    border: none;
    font-size: 18px;
    cursor: pointer;
    line-height: 1;
    z-index: 1;
  }}
  #modal-image {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }}
  .modal-body {{ padding: 22px 24px 26px; }}
  #modal-badge {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 700;
    color: #fff;
    padding: 3px 9px;
    border-radius: 4px;
    margin-bottom: 10px;
  }}
  #modal-title {{ font-family: var(--font-serif); font-size: 24px; font-weight: 700; margin: 0 0 12px; line-height: 1.3; }}
  #modal-description {{ font-size: 15px; line-height: 1.7; color: #333; margin: 0 0 18px; white-space: pre-line; }}
  #modal-source {{ font-family: var(--font-mono); font-size: 12px; color: var(--muted); margin-bottom: 18px; }}
  #modal-link {{
    display: inline-block;
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 14px;
    color: #fff;
    background: var(--text);
    padding: 10px 18px;
    border-radius: 999px;
    text-decoration: none;
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>오늘의 브리핑</h1>
    <hr class="rule">
    <div class="meta">
      <span class="date">{today}</span>
      <span class="badge">09:00 KST 갱신</span>
    </div>
  </header>
  <nav class="cat-nav">
    {cat_nav}
  </nav>
  <main class="grid">
    {columns}
  </main>
  <footer>매일 아침 자동 생성됩니다.</footer>
</div>

<div id="modal-overlay">
  <div class="modal">
    <button class="modal-close" onclick="closeBriefingModal()">&times;</button>
    <img id="modal-image" src="" alt="">
    <div class="modal-body">
      <span id="modal-badge"></span>
      <h2 id="modal-title"></h2>
      <p id="modal-description"></p>
      <div id="modal-source"></div>
      <a id="modal-link" href="#" target="_blank" rel="noopener">원문 전체 보기 ↗</a>
    </div>
  </div>
</div>

<script type="application/json" id="articles-data">{articles_json}</script>
<script>
(function() {{
  var ARTICLES = JSON.parse(document.getElementById('articles-data').textContent);
  var overlay = document.getElementById('modal-overlay');

  function openModal(data, href) {{
    var img = document.getElementById('modal-image');
    if (data.image) {{ img.src = data.image; img.style.display = 'block'; }}
    else {{ img.style.display = 'none'; }}
    var badge = document.getElementById('modal-badge');
    badge.textContent = data.badge;
    badge.style.background = data.accent;
    document.getElementById('modal-title').textContent = data.title;
    document.getElementById('modal-description').textContent = data.description || '요약 정보가 없습니다. 원문에서 확인해주세요.';
    document.getElementById('modal-source').textContent = data.sourceLine;
    document.getElementById('modal-link').href = href;
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }}

  window.closeBriefingModal = function() {{
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  }};

  document.addEventListener('click', function(e) {{
    var link = e.target.closest('.card');
    if (!link) return;
    var id = link.getAttribute('data-article-id');
    var data = ARTICLES[id];
    if (!data) return;
    e.preventDefault();
    openModal(data, link.href);
  }});

  overlay.addEventListener('click', function(e) {{
    if (e.target === overlay) window.closeBriefingModal();
  }});
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') window.closeBriefingModal();
  }});
}})();
</script>
</body>
</html>
"""


def _source_domain(url: str) -> str:
    netloc = urlparse(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc


def _source_line(article: Article) -> str:
    domain = _source_domain(article.link)
    time_str = article.published_at.astimezone(KST).strftime("%H:%M")
    return f"{domain} · {time_str}"


def _category_emoji(label: str) -> str:
    return label.split(" ", 1)[0] if " " in label else label


class _ArticleRegistry:
    """카드 클릭 시 JS 모달에 넘길 기사 데이터를 id로 모아둔다."""

    def __init__(self) -> None:
        self._items: List[dict] = []

    def add(self, article: Article, badge: str, accent: str, image_url: Optional[str]) -> int:
        article_id = len(self._items)
        self._items.append(
            {
                "title": article.title,
                "description": article.description,
                "sourceLine": _source_line(article),
                "badge": badge,
                "accent": accent,
                "image": image_url,
            }
        )
        return article_id

    def to_json(self) -> str:
        # </script> 이스케이프로 임베드된 <script> 태그가 조기 종료되는 것을 방지
        return json.dumps(self._items, ensure_ascii=False).replace("</", "<\\/")


def _render_card(
    article: Article,
    is_headline: bool,
    headline_source: str,
    image_url: Optional[str],
    emoji: str,
    accent: str,
    registry: "_ArticleRegistry",
) -> str:
    link = escape(article.link, quote=True)
    title = escape(article.title)
    description = escape(article.description) if article.description else ""
    badge_text = headline_source if is_headline else "언론사"
    badge_html = (
        f'<span class="badge-headline">{escape(badge_text)}</span>'
        if is_headline
        else f'<span class="badge-source">{escape(badge_text)}</span>'
    )
    card_class = "card headline" if is_headline else "card"

    if image_url:
        thumb_html = f'<div class="thumb"><img src="{escape(image_url, quote=True)}" loading="lazy" alt=""></div>'
    else:
        thumb_html = f'<div class="thumb"><div class="thumb-placeholder">{escape(emoji)}</div></div>'

    article_id = registry.add(article, badge_text, accent, image_url)

    return (
        f'<a class="{card_class}" href="{link}" target="_blank" rel="noopener" data-article-id="{article_id}">'
        f"{thumb_html}"
        f'<div class="card-body">{badge_html}'
        f'<h3 class="title">{title}</h3>'
        + (f'<p class="description">{description}</p>' if description else "")
        + f'<div class="source-line">{escape(_source_line(article))}</div>'
        f"</div></a>"
    )


def _format_stat_value(indicator: Indicator) -> str:
    if "환율" in indicator.label:
        return f"{indicator.value:,.1f}원"
    if "기준금리" in indicator.label:
        return f"{indicator.value:.2f}%"
    return f"{indicator.value:,.2f}"


def _render_stat_row(indicator: Indicator) -> str:
    emphasize = indicator.change_pct is not None and abs(indicator.change_pct) >= _ECOS_EMPHASIZE_THRESHOLD
    row_class = "stat-row emphasize" if emphasize else "stat-row"

    change_html = ""
    if indicator.change_pct is not None:
        direction = "up" if indicator.change_pct >= 0 else "down"
        sign = "+" if indicator.change_pct >= 0 else ""
        change_html = f'<span class="stat-change {direction}">{sign}{indicator.change_pct:.2f}%</span>'

    return (
        f'<div class="{row_class}">'
        f'<span class="stat-label">{escape(indicator.label)}</span>'
        f'<span class="stat-value">{escape(_format_stat_value(indicator))}</span>'
        f"{change_html}"
        f"</div>"
    )


def _render_stat_block(snapshot: EcosSnapshot) -> str:
    indicators = (snapshot.kospi, snapshot.kosdaq, snapshot.usd_krw, snapshot.base_rate)
    rows = "".join(_render_stat_row(i) for i in indicators)
    as_of = snapshot.kospi.as_of
    as_of_fmt = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}" if len(as_of) == 8 else as_of
    return f'<div class="stat-block">{rows}<div class="stat-source">한국은행(ECOS) 공식 통계 · {escape(as_of_fmt)} 기준</div></div>'


def _render_column(
    briefing: CategoryBriefing,
    ecos_snapshot: Optional[EcosSnapshot],
    image_map: Dict[str, str],
    registry: "_ArticleRegistry",
) -> str:
    label = escape(briefing.category.label)
    color = escape(briefing.category.color, quote=True)
    emoji = _category_emoji(briefing.category.label)
    anchor = escape(briefing.category.key, quote=True)

    stat_html = ""
    if briefing.category.key == "economy" and ecos_snapshot is not None:
        stat_html = _render_stat_block(ecos_snapshot)

    if briefing.headline is None:
        body = '<p class="empty">관련 소식을 찾지 못했습니다.</p>'
    else:
        cards = [
            _render_card(
                briefing.headline,
                True,
                briefing.headline_source,
                image_map.get(briefing.headline.link),
                emoji,
                briefing.category.color,
                registry,
            )
        ]
        cards += [
            _render_card(article, False, "", image_map.get(article.link), emoji, briefing.category.color, registry)
            for article in briefing.rest
        ]
        body = "\n".join(cards)

    return (
        f'<section class="column" id="cat-{anchor}" style="--accent: {color}">'
        f"<h2>{label}</h2>{stat_html}{body}</section>"
    )


def render_page(
    briefings: List[CategoryBriefing],
    today: str,
    ecos_snapshot: Optional[EcosSnapshot] = None,
    image_map: Optional[Dict[str, str]] = None,
) -> str:
    """카테고리별 헤드라인/기사 목록과 경제 지표를 담은 단일 HTML 페이지 문자열을 생성합니다."""
    image_map = image_map or {}
    registry = _ArticleRegistry()

    columns = "\n".join(_render_column(b, ecos_snapshot, image_map, registry) for b in briefings)

    cat_nav = "\n".join(
        f'<a href="#cat-{escape(b.category.key, quote=True)}" style="--accent: {escape(b.category.color, quote=True)}">'
        f"{escape(b.category.label)}</a>"
        for b in briefings
    )

    return _PAGE_TEMPLATE.format(
        title=f"오늘의 브리핑 - {today}",
        today=escape(today),
        cat_nav=cat_nav,
        columns=columns,
        articles_json=registry.to_json(),
    )


def write_page(html: str, output_path: Path = Path("docs/index.html")) -> None:
    """생성된 HTML을 파일로 저장합니다 (상위 폴더가 없으면 생성)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
