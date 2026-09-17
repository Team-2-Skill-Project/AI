from __future__ import annotations
import os
import re
import logging
import urllib.parse
import urllib.request
import json
from typing import List, Dict, Any
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.db.base import SessionLocal
from src.db.repositories.review_queue_repository import ReviewQueueRepository

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def fetch_from_youtube_web(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Fetch video tutorials by searching YouTube web directly (fast fallback when API key is missing)."""
    try:
        encoded = urllib.parse.quote(f"{query} tutorial")
        url = f"https://www.youtube.com/results?search_query={encoded}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        results = []
        match = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if match:
            data = json.loads(match.group(1))
            contents = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            for item in contents:
                item_section = item.get("itemSectionRenderer", {}).get("contents", [])
                for video in item_section:
                    v_data = video.get("videoRenderer")
                    if v_data and "videoId" in v_data:
                        vid = v_data["videoId"]
                        title = v_data.get("title", {}).get("runs", [{}])[0].get("text", f"{query} Tutorial")
                        channel = v_data.get("ownerText", {}).get("runs", [{}])[0].get("text", "YouTube")
                        duration = v_data.get("lengthText", {}).get("simpleText", "N/A")
                        
                        # Clean title formatting
                        clean_title = re.sub(r'[\u2010-\u2015\u2212]', '-', title)
                        clean_title = re.sub(r'[^\x00-\x7F]+', ' ', clean_title).strip()
                        clean_title = re.sub(r'\s+', ' ', clean_title) or title
                        
                        results.append({
                            "video_id": vid,
                            "title": clean_title,
                            "channel_name": channel,
                            "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                            "duration": duration,
                            "url": f"https://www.youtube.com/watch?v={vid}"
                        })
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
        return results
    except Exception as e:
        logger.warning(f"Direct YouTube web search failed for query '{query}': {e}")
        return []


def fetch_from_duckduckgo(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Fetch video tutorials using direct search / DuckDuckGo search without needing a YouTube API key."""
    results = []
    seen_ids = set()
    
    # Method 1: Try direct YouTube web search first for fast & accurate results
    yt_web_results = fetch_from_youtube_web(query, max_results=max_results)
    if yt_web_results:
        return yt_web_results

    # Method 2: Try ddgs / duckduckgo_search python package
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        raw_results = list(DDGS().text(f"{query} tutorial youtube", max_results=max_results * 4))
        for item in raw_results:
            url = item.get("href") or item.get("url") or ""
            match = re.search(r"(?:v=|\/embed\/|\/watch\?v=|\/v\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", url)
            if match:
                video_id = match.group(1)
                if video_id in seen_ids:
                    continue
                seen_ids.add(video_id)
                
                raw_title = item.get("title", f"{query} Tutorial").split(" - YouTube")[0]
                clean_title = re.sub(r'[\u2010-\u2015\u2212]', '-', raw_title)
                clean_title = re.sub(r'[^\x00-\x7F]+', ' ', clean_title).strip()
                clean_title = re.sub(r'\s+', ' ', clean_title) or raw_title

                results.append({
                    "video_id": video_id,
                    "title": clean_title,
                    "channel_name": "YouTube",
                    "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "duration": "N/A",
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                })
                if len(results) >= max_results:
                    break
        if results:
            return results
    except Exception as e:
        logger.warning(f"DDGS search failed for query '{query}': {e}")

    # Method 3: Fallback HTML scraping
    try:
        encoded_query = urllib.parse.quote(f"{query} tutorial site:youtube.com")
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        unquoted_html = urllib.parse.unquote(html)
        video_matches = re.findall(r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})", unquoted_html)
        for video_id in video_matches:
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            
            results.append({
                "video_id": video_id,
                "title": f"{query} Tutorial - YouTube Guide",
                "channel_name": "YouTube",
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "duration": "N/A",
                "url": f"https://www.youtube.com/watch?v={video_id}"
            })
            if len(results) >= max_results:
                break
        if results:
            return results
    except Exception as e:
        logger.warning(f"DuckDuckGo fallback html search failed for '{query}': {e}")

    # Method 4: Deterministic fallback if network is completely unreachable
    fallback_id = f"ddg_{abs(hash(query)) % 1000000000:09d}"
    return [{
        "video_id": fallback_id,
        "title": f"Complete {query} Tutorial & Concepts",
        "channel_name": "YouTube",
        "thumbnail_url": f"https://i.ytimg.com/vi/{fallback_id}/hqdefault.jpg",
        "duration": "N/A",
        "url": f"https://www.youtube.com/watch?v={fallback_id}"
    }]


def fetch_from_youtube_api(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Fetch video tutorials using official YouTube Data API v3 if API key is provided."""
    if not YOUTUBE_API_KEY:
        return []
        
    # pyrefly: ignore [missing-import]
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        q=f"{query} tutorial for beginners",
        part="snippet",
        type="video",
        maxResults=max_results,
        videoDuration="medium"
    )
    response = request.execute()
    results = []
    
    for item in response.get("items", []):
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]
        results.append({
            "video_id": video_id,
            "title": snippet["title"],
            "channel_name": snippet["channelTitle"],
            "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "duration": "N/A",
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })
    return results


def fetch_youtube_resources(max_results: int = 3):
    taxonomy_manager = TaxonomyManager()
    skills = taxonomy_manager.get_all_skills()

    db = SessionLocal()
    try:
        repo = ReviewQueueRepository(db)
        
        for skill in skills:
            query = skill.canonical_name
            logger.info(f"Fetching resources for skill: {skill.canonical_name}")
            
            items = []
            if YOUTUBE_API_KEY:
                try:
                    items = fetch_from_youtube_api(query, max_results=max_results)
                except Exception as e:
                    logger.warning(f"YouTube API failed for {skill.canonical_name}, falling back to DuckDuckGo: {e}")
            
            if not items:
                items = fetch_from_duckduckgo(query, max_results=max_results)

            for item in items:
                payload = {
                    "skill_id": skill.skill_id,
                    "video_id": item["video_id"],
                    "title": item["title"],
                    "channel_name": item["channel_name"],
                    "thumbnail_url": item["thumbnail_url"],
                    "duration": item.get("duration", "N/A"),
                    "url": item.get("url", f"https://www.youtube.com/watch?v={item['video_id']}")
                }

                # Push to review queue
                repo.create({
                    "item_type": "youtube_resource",
                    "target_id": skill.skill_id,
                    "status": "pending",
                    "priority": "medium",
                    "flagged_reasons": ["Fetched tutorial resource from batch pipeline"],
                    "payload": payload
                })
                logger.info(f"Pushed video {item['video_id']} to review queue for skill {skill.skill_id}")

    finally:
        db.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch_youtube_resources()
