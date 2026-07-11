"""
빅테크 공식 블로그 헤드라인(영어)을 한국어로 번역하는 모듈

네이버 파파고의 무료 Open API는 서비스가 종료되어(2026-07 확인), 비공식
구글 번역 웹 인터페이스를 사용하는 deep-translator 라이브러리를 씁니다.
비공식 서비스라 언제든 실패할 수 있으므로, 실패 시 원문을 그대로 반환해
파이프라인이 멈추지 않게 합니다.
"""
import logging

from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)


def translate_to_korean(text: str) -> str:
    """영어 텍스트를 한국어로 번역합니다. 실패하면 원문을 그대로 반환합니다."""
    if not text:
        return text
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text)
    except Exception:
        logger.warning("번역 실패, 원문을 그대로 사용합니다: %s", text)
        return text
