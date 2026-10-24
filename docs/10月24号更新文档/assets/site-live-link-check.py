"""Read-only public link checks, gated on a confirmed Pages deployment."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, ProxyHandler, build_opener

BASE = 'https://coscatld.github.io/MathTutor/'


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for key, value in attrs if key == 'href' and value)


def main():
    if os.environ.get('MATHTUTOR_SITE_DEPLOYED') != 'yes':
        raise SystemExit('Run only after confirmed deployment')
    commit = os.environ.get('MATHTUTOR_DEPLOYMENT_COMMIT')
    if not commit:
        raise SystemExit('MATHTUTOR_DEPLOYMENT_COMMIT is required')
    exported = Path(sys.argv[1])
    if not (exported / 'zh/index.html').is_file():
        raise SystemExit('Expected the matching local site export')
    targets = set()
    pages = list(exported.rglob('*.html'))
    for page in pages:
        parser = Anchors()
        parser.feed(page.read_text(encoding='utf-8'))
        relative = page.relative_to(exported).as_posix()
        page_url = urljoin(BASE, relative.removesuffix('index.html'))
        for href in parser.hrefs:
            url = urldefrag(urljoin(page_url, href))[0]
            parts = urlsplit(url)
            if parts.scheme == 'https' and parts.netloc == 'coscatld.github.io' and parts.path.startswith('/MathTutor/'):
                targets.add(url)
    if not targets:
        raise SystemExit('No public internal targets found')

    def check(url):
        try:
            request = Request(url, headers={'User-Agent': 'MathTutor-public-release-acceptance'})
            # Uses normal certificate/hostname verification; no credentials.
            with build_opener(ProxyHandler({})).open(request, timeout=30) as response:
                response.read(256)
                return {'url': url, 'status': response.status, 'final_url': response.url,
                        'content_type': response.headers.get('Content-Type', '')}
        except Exception as error:
            return {'url': url, 'error': str(error)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, sorted(targets)))
    failures = [row for row in results if row.get('status') != 200]
    report = {'at': datetime.now(timezone.utc).isoformat(), 'commit': commit,
              'scope': 'Public HTTP GET for internal anchor targets enumerated from the matching local static export; fragments and external links excluded',
              'source_html_files': len(pages), 'targets': len(results),
              'status': 'FAIL' if failures else 'PASS', 'failures': failures, 'results': results}
    Path(__file__).with_name('site-live-links.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
