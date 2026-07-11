"""
기사 원문 페이지의 대표 이미지(og:image)를 가져오는 모듈

카카오톡/소셜 링크 공유 미리보기와 같은 원리 — 기사 본문을 복제하지 않고
공개된 소셜 미리보기용 메타태그만 읽어 썸네일로 쓴다. 전체가 best-effort이며,
개별 사이트가 느리거나 실패해도 예외를 삼키고 건너뛰어 파이프라인은 계속 진행된다.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from news_service import Article

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 5  # 이미지 조회는 부가 기능이라 핵심 데이터 수집보다 짧게 잡는다
_MAX_BYTES = 200_000  # og:image는 보통 <head> 안에 있으므로 앞부분만 읽으면 충분
_MAX_WORKERS = 8


def fetch_og_image(url: str) -> Optional[str]:
    """기사 원문 페이지에서 og:image(없으면 twitter:image) URL을 가져옵니다. 실패하면 None."""
    try:
        response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, stream=True)
        content = b""
        for chunk in response.iter_content(chunk_size=8192):
            content += chunk
            if len(content) >= _MAX_BYTES:
                break
        response.close()
    except requests.RequestException:
        return None

    try:
        soup = BeautifulSoup(content, "html.parser")
    except Exception:
        return None

    tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def fetch_images(articles: List[Article]) -> Dict[str, str]:
    """기사 목록의 링크별 대표 이미지 URL을 병렬로 조회합니다 (실패한 기사는 결과에서 빠짐)."""
    images: Dict[str, str] = {}
    if not articles:
        return images

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        future_to_link = {executor.submit(fetch_og_image, article.link): article.link for article in articles}
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            try:
                image_url = future.result()
            except Exception:
                logger.debug("이미지 조회 실패, 건너뜁니다: %s", link)
                continue
            if image_url:
                images[link] = image_url

    logger.info("기사 대표 이미지 %d/%d건 확보", len(images), len(articles))
    return images
