import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


API_BASE = "https://api.supadata.ai/v1"


def extract_video_id(youtube_url: str) -> str:
    parsed = urlparse(youtube_url)
    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or "youtube-video"
    if "youtube.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        if "v" in query and query["v"]:
            return query["v"][0]
    return "youtube-video"


def sanitize_filename(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "youtube-transcript"


def request_json(url: str, api_key: str) -> tuple[int, dict]:
    req = Request(
        url=url,
        headers={
            "x-api-key": api_key,
            "accept": "application/json",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )
    with urlopen(req) as response:
        status = response.getcode()
        body = response.read().decode("utf-8")
        data = json.loads(body) if body else {}
        return status, data


def fetch_transcript(youtube_url: str, api_key: str, text_mode: bool = False) -> dict:
    params = {"url": youtube_url, "mode": "auto"}
    if text_mode:
        params["text"] = "true"
    url = f"{API_BASE}/transcript?{urlencode(params)}"

    status, data = request_json(url, api_key)
    if status == 202:
        job_id = data.get("jobId")
        if not job_id:
            raise RuntimeError("Supadata returned 202 without a jobId.")
        poll_url = f"{API_BASE}/transcript/{job_id}"
        for _ in range(60):
            time.sleep(2)
            poll_status, poll_data = request_json(poll_url, api_key)
            if poll_status == 202:
                continue
            return poll_data
        raise TimeoutError("Timed out waiting for Supadata transcript job completion.")
    return data


def format_markdown(source_url: str, transcript_data: dict) -> str:
    lang = transcript_data.get("lang", "unknown")
    segments = transcript_data.get("content", [])

    lines = [
        "# YouTube Transcript",
        "",
        f"- Source URL: {source_url}",
        f"- Language: {lang}",
        "",
        "## Transcript",
        "",
    ]

    if isinstance(segments, str):
        lines.append(segments.strip())
    elif isinstance(segments, list):
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            offset = segment.get("offset")
            if offset is not None:
                lines.append(f"- [{offset:.2f}s] {text}")
            else:
                lines.append(f"- {text}")
    else:
        lines.append("_No transcript content returned._")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch YouTube transcript from Supadata API and save as Markdown.")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--api-key", default=os.environ.get("SUPADATA_API_KEY"), help="Supadata API key")
    parser.add_argument(
        "--out-dir",
        default="research/youtube-transcripts",
        help="Output directory for markdown transcript",
    )
    parser.add_argument("--text-mode", action="store_true", help="Request plain text transcript from API")
    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("Missing API key. Provide --api-key or SUPADATA_API_KEY environment variable.")

    transcript_data = fetch_transcript(args.url, args.api_key, text_mode=args.text_mode)
    markdown = format_markdown(args.url, transcript_data)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = sanitize_filename(extract_video_id(args.url)) + ".md"
    output_path = out_dir / filename
    output_path.write_text(markdown, encoding="utf-8")

    print(f"Transcript saved to: {output_path}")


if __name__ == "__main__":
    main()
